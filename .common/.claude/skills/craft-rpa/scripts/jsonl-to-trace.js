#!/usr/bin/env node
/**
 * jsonl-to-trace —— 把 oracle-register-recorder 录制的 session.jsonl
 * 转换为 AI 友好的 markdown 流程参考文档(机械翻译,不做语义识别)。
 *
 * 与 jsonl-to-playwright.js 的关键差异:
 *   - js 只做"机械翻译":每条事件平铺,字段全保留,不删任何信息
 *   - 不过滤、不合并、不命名 step —— 这些都由 AI 在 LLM 精修阶段做
 *     (理由:step 的业务命名 / 噪音判定需要业务上下文,js 不知道)
 *   - 不脱敏:假设 inject.js 已禁用 REDACT_SENSITIVE
 *
 * 输出结构:
 *   1. 头部元数据 —— 起止时间 / 时长 / 事件总数 / URL 覆盖 / kind.type 分布
 *   2. 速览表    —— 每事件一行(#/t+s/kind.type/简述/最稳selector/value 或 URL)
 *   3. 事件详情  —— 每事件一段,字段全保留(selectors 全集 / state / boundingBox / network / 祖先链 ...)
 *
 * 超长 URL 处理(防止 token URL 暴击 markdown 体积):
 *   - 详情段 url / requestUrl / to / from / referrer 字段超过 --max-url-len(默认 800)截断
 *   - 截断格式:`<前 70%>…<后 30%>` + 标注 `(truncated: 总长 N → M, full at jsonl#L)`
 *   - 每条事件标注 `jsonlLine: <N>`(1-based),反查命令:
 *       sed -n '<N>p' <session.jsonl> | jq .url
 *
 * 用法:
 *   node jsonl-to-trace.js [--max-url-len <N>] <input.jsonl> [output.md]
 *   cat session.jsonl | node jsonl-to-trace.js [--max-url-len <N>]
 */

const fs = require('fs');
const path = require('path');

const DEFAULT_MAX_URL_LEN = 800;

// ========== CLI ==========
(async () => {
    const argv = process.argv.slice(2);

    let inputPath = null;
    let outputPath = null;
    let maxUrlLen = DEFAULT_MAX_URL_LEN;

    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === '--max-url-len') {
            const v = parseInt(argv[++i], 10);
            if (!Number.isFinite(v) || v < 100) {
                process.stderr.write('[err] --max-url-len 必须是 ≥ 100 的整数\n');
                process.exit(2);
            }
            maxUrlLen = v;
        } else if (a === '-h' || a === '--help') {
            printHelp();
            process.exit(0);
        } else if (a.startsWith('-')) {
            process.stderr.write(`[err] unknown option: ${a}\n`);
            process.exit(2);
        } else if (!inputPath) {
            inputPath = a;
        } else if (!outputPath) {
            outputPath = a;
        }
    }

    if (!inputPath && process.stdin.isTTY) {
        printHelp();
        process.exit(2);
    }

    let raw;
    if (inputPath) {
        if (!fs.existsSync(inputPath)) {
            process.stderr.write(`[err] input not found: ${inputPath}\n`);
            process.exit(2);
        }
        raw = fs.readFileSync(inputPath, 'utf8');
    } else {
        raw = await readStdin();
    }

    const events = parseJsonl(raw);
    const md = generateTrace(events, { inputPath, maxUrlLen });

    if (outputPath) {
        fs.writeFileSync(outputPath, md);
        process.stderr.write(`[ok] wrote ${outputPath} (${events.length} events, maxUrlLen=${maxUrlLen})\n`);
    } else {
        process.stdout.write(md);
    }
})().catch(err => {
    process.stderr.write(`[err] ${err.stack || err.message}\n`);
    process.exit(1);
});

function printHelp() {
    process.stderr.write([
        'Usage: node jsonl-to-trace.js [--max-url-len <N>] <input.jsonl> [output.md]',
        '   or: cat session.jsonl | node jsonl-to-trace.js [--max-url-len <N>]',
        '',
        'Options:',
        '  --max-url-len <N>   单个 URL 字段最大长度(默认 800),超过则截断 + 标注反查行号',
        '  -h, --help          打印此帮助',
        '',
    ].join('\n'));
}

// ========== IO ==========

function readStdin() {
    return new Promise((resolve, reject) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', chunk => { data += chunk; });
        process.stdin.on('end', () => resolve(data));
        process.stdin.on('error', reject);
    });
}

function parseJsonl(raw) {
    const lines = raw.split('\n');  // 不 filter,保留 1-based 原始行号
    const events = [];
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (!line.trim()) continue;
        try {
            const ev = JSON.parse(line);
            ev.__jsonlLine = i + 1;  // 1-based;反查 `sed -n '<N>p' session.jsonl`
            events.push(ev);
        } catch (e) {
            process.stderr.write(`[warn] skip malformed line ${i + 1}: ${line.slice(0, 80)}\n`);
        }
    }
    events.sort((a, b) => {
        const ta = a.serverTime || a.clientTime || '';
        const tb = b.serverTime || b.clientTime || '';
        return ta.localeCompare(tb);
    });
    return events;
}

// ========== 主转换 ==========

function generateTrace(events, ctx) {
    if (events.length === 0) {
        return '# Session Trace\n\n(empty: no events recorded)\n';
    }

    const first = events[0];
    const last = events[events.length - 1];
    const t0Iso = first.serverTime || first.clientTime || '';
    const tEndIso = last.serverTime || last.clientTime || '';
    const t0 = new Date(t0Iso).getTime() || 0;
    const tEnd = new Date(tEndIso).getTime() || 0;
    const duration = Math.max(0, (tEnd - t0) / 1000);

    // URL 覆盖(去 query + 去 hash 去重)
    const urls = new Set();
    for (const ev of events) {
        if (ev.url) urls.add(stripQueryAndHash(ev.url));
    }

    // kind.type 计数
    const kindCounts = {};
    for (const ev of events) {
        const key = `${ev.kind}.${ev.type}`;
        kindCounts[key] = (kindCounts[key] || 0) + 1;
    }

    // 统计超长 URL 数
    let truncatedCount = 0;
    for (const ev of events) {
        for (const k of ['url', 'requestUrl', 'to', 'from', 'referrer']) {
            if (ev[k] && String(ev[k]).length > ctx.maxUrlLen) truncatedCount++;
        }
    }

    const lines = [];

    // ---------- 1. 头部元数据 ----------
    lines.push('# Session Trace');
    if (ctx.inputPath) lines.push(`> source: \`${path.basename(ctx.inputPath)}\``);
    lines.push('');
    lines.push(`- 起止时间: \`${t0Iso}\` → \`${tEndIso}\``);
    lines.push(`- 时长: \`${formatDuration(duration)}\``);
    lines.push(`- 事件总数: **${events.length}**`);
    lines.push(`- 超长 URL 截断: ${truncatedCount} 处(阈值 maxUrlLen=${ctx.maxUrlLen};完整原文在原 jsonl,通过 jsonlLine 反查)`);
    lines.push(`- URL 覆盖(去 query+hash):`);
    for (const u of urls) lines.push(`  - \`${u}\``);
    lines.push(`- 事件类型分布(降序):`);
    const sortedKinds = Object.entries(kindCounts).sort((a, b) => b[1] - a[1]);
    for (const [k, v] of sortedKinds) lines.push(`  - \`${k}\`: ${v}`);
    lines.push('');
    lines.push('> **本文是机械翻译,不做语义合并 / step 命名 / 噪音过滤。**');
    lines.push('> AI 精修阶段应:识别业务步骤、合并相邻事件、给步骤起业务名、标注噪音(但不删原文)、输出 RPA 改造草案。');
    lines.push('>');
    lines.push('> **超长 URL 反查**:每条事件标注 `jsonlLine: <N>`(1-based);取原文用:');
    lines.push('> ```bash');
    lines.push('> sed -n \'<N>p\' <session.jsonl> | jq .url');
    lines.push('> # 或字段名换成 .requestUrl / .to / .from / .referrer');
    lines.push('> ```');
    lines.push('');

    // ---------- 2. 速览表 ----------
    lines.push('## 速览表');
    lines.push('');
    lines.push('便于 AI 整体把握流程;详情看下面"事件详情"段。');
    lines.push('');
    lines.push('| # | jsonl# | t+s | kind.type | 简述 | 最稳selector | value/URL |');
    lines.push('|---|--------|-----|-----------|------|--------------|-----------|');
    for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        const tEv = new Date(ev.serverTime || ev.clientTime || 0).getTime() || t0;
        const offset = ((tEv - t0) / 1000).toFixed(1);
        const desc = describeBrief(ev);
        const sel = stableSelector(ev.target);
        const valOrUrl = valueOrUrl(ev);
        lines.push(`| ${i + 1} | ${ev.__jsonlLine || ''} | ${offset} | \`${ev.kind}.${ev.type}\` | ${esc(desc)} | ${esc(sel)} | ${esc(valOrUrl)} |`);
    }
    lines.push('');

    // ---------- 3. 事件详情 ----------
    lines.push('## 事件详情');
    lines.push('');
    lines.push('每条事件一段,字段全保留(target.selectors 全集 / accessibleName / state / boundingBox / 网络 / 祖先链 ...)。');
    lines.push('超长 URL 已按 maxUrlLen 截断,反查方式见头部说明。');
    lines.push('');

    for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        const tEv = new Date(ev.serverTime || ev.clientTime || 0).getTime() || t0;
        const offset = ((tEv - t0) / 1000).toFixed(1);
        lines.push(`### #${i + 1} \`${ev.kind}.${ev.type}\` @ +${offset}s`);
        lines.push('');
        lines.push(...renderEvent(ev, ctx));
        lines.push('');
    }

    return lines.join('\n');
}

// ========== 单事件详细渲染 ==========

function renderEvent(ev, ctx) {
    const out = [];
    out.push(`- jsonlLine: ${ev.__jsonlLine || '?'}`);

    const urlLine = urlField('url', ev.url, ctx, ev.__jsonlLine);
    if (urlLine) out.push(urlLine);

    if (ev.sessionId) out.push(`- sessionId: \`${ev.sessionId}\``);
    if (ev.clientTime) out.push(`- clientTime: \`${ev.clientTime}\``);
    if (ev.serverTime) out.push(`- serverTime: \`${ev.serverTime}\``);
    if (ev.frame && ev.frame.inIframe) {
        out.push(`- frame: iframe depth=${ev.frame.depth} path=\`${JSON.stringify(ev.frame.framePath || [])}\``);
    }

    // target 完整字段
    if (ev.target) {
        const t = ev.target;
        const tagDesc = `${t.tag || ''}${t.type ? `[type=${t.type}]` : ''}`;
        out.push(`- 元素: \`${tagDesc}\``);
        if (t.accessibleName) out.push(`- accessibleName: "${truncate(t.accessibleName, 200)}"`);
        if (t.innerText && t.innerText !== t.accessibleName) out.push(`- innerText: "${truncate(t.innerText, 200)}"`);
        if (t.textContent && t.textContent !== t.innerText) out.push(`- textContent: "${truncate(t.textContent, 200)}"`);
        if (t.role) out.push(`- role: \`${t.role}\``);
        if (t.id) out.push(`- id: \`${t.id}\``);
        if (t.name) out.push(`- name(prop): \`${t.name}\``);
        if (t.classes && t.classes.length) out.push(`- classes: \`${t.classes.join(' ')}\``);
        if (t.sensitive) out.push(`- **sensitive: true** (inject.js 命中敏感字段规则;value 已透传原值,REDACT_SENSITIVE=true 时才脱敏)`);

        if (t.selectors) {
            out.push(`- 选择器全集:`);
            for (const [k, v] of Object.entries(t.selectors)) {
                if (v) out.push(`  - \`${k}\`: \`${v}\``);
            }
        }

        if (t.state) {
            const s = Object.entries(t.state)
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => `${k}=${v}`).join(', ');
            if (s) out.push(`- state: ${s}`);
        }
        if (t.boundingBox) {
            const b = t.boundingBox;
            out.push(`- boundingBox: x=${b.x} y=${b.y} w=${b.width} h=${b.height}`);
        }
        if (t.attributes && Object.keys(t.attributes).length) {
            const attrs = Object.entries(t.attributes).map(([k, v]) => `${k}="${v}"`).join(' ');
            out.push(`- attributes: \`${attrs}\``);
        }
        if (t.ancestors && t.ancestors.length) {
            const anc = t.ancestors.map(a => {
                const parts = [a.tag || '?'];
                if (a.id) parts.push(`#${a.id}`);
                if (a.role) parts.push(`[role=${a.role}]`);
                if (a.testId) parts.push(`[testId="${a.testId}"]`);
                if (a.classes && a.classes.length) parts.push(`.${a.classes.slice(0, 2).join('.')}`);
                return parts.join('');
            }).join(' > ');
            out.push(`- ancestors: \`${anc}\``);
        }
    }

    // interaction 特殊字段
    if (ev.kind === 'interaction') {
        if (ev.value !== undefined && ev.value !== null) {
            const v = typeof ev.value === 'string' ? truncate(ev.value, 300) : JSON.stringify(ev.value);
            out.push(`- value: \`${v}\``);
        }
        if (ev.valueLength !== undefined) out.push(`- valueLength: ${ev.valueLength}`);
        if (ev.checked !== undefined && ev.checked !== null) out.push(`- checked: ${ev.checked}`);
        if (ev.selectedText) out.push(`- selectedText: "${ev.selectedText}"`);
        if (ev.formFields && ev.formFields.length) {
            out.push(`- formFields:`);
            for (const f of ev.formFields) {
                const tags = [];
                if (f.type) tags.push(`type=${f.type}`);
                if (f.valueLength !== undefined) tags.push(`len=${f.valueLength}`);
                if (f.sensitive) tags.push('sensitive');
                out.push(`  - \`${f.name || '(no-name)'}\` (${f.tag}${tags.length ? ', ' + tags.join(', ') : ''})`);
            }
        }
        if (ev.mouse) {
            const m = ev.mouse;
            out.push(`- mouse: page(${m.pageX},${m.pageY}) client(${m.clientX},${m.clientY}) offset(${m.offsetX},${m.offsetY}) button=${m.button}`);
        }
        if (ev.modifiers) {
            const mods = Object.entries(ev.modifiers).filter(([, v]) => v).map(([k]) => k);
            if (mods.length) out.push(`- modifiers: ${mods.join('+')}`);
        }
        if (ev.key) out.push(`- key: \`${ev.key}\` (code=\`${ev.code || ''}\`)`);
        if (ev.viewport) {
            const vp = ev.viewport;
            out.push(`- viewport: ${vp.width}×${vp.height} scroll(${vp.scrollX},${vp.scrollY}) dpr=${vp.dpr}`);
        }
    }

    // network
    if (ev.kind === 'network') {
        if (ev.method) out.push(`- method: \`${ev.method}\``);
        const reqLine = urlField('requestUrl', ev.requestUrl, ctx, ev.__jsonlLine);
        if (reqLine) out.push(reqLine);
        if (ev.status !== undefined) out.push(`- status: ${ev.status}`);
        if (ev.durationMs !== undefined) out.push(`- durationMs: ${ev.durationMs}`);
        if (ev.error) out.push(`- error: \`${ev.error}\``);
    }

    // navigation
    if (ev.kind === 'navigation') {
        const fromLine = urlField('from', ev.from, ctx, ev.__jsonlLine);
        if (fromLine) out.push(fromLine);
        const toLine = urlField('to', ev.to, ctx, ev.__jsonlLine);
        if (toLine) out.push(toLine);
        if (ev.title) out.push(`- title: "${truncate(ev.title, 200)}"`);
        const refLine = urlField('referrer', ev.referrer, ctx, ev.__jsonlLine);
        if (refLine) out.push(refLine);
        if (ev.userAgent) out.push(`- userAgent: \`${truncate(ev.userAgent, 120)}\``);
        if (ev.viewport) {
            const vp = ev.viewport;
            out.push(`- viewport: ${vp.width}×${vp.height} dpr=${vp.dpr}`);
        }
    }

    // error
    if (ev.kind === 'error') {
        if (ev.message) out.push(`- message: \`${truncate(ev.message, 300)}\``);
        if (ev.source) out.push(`- source: \`${ev.source}\``);
        if (ev.line !== undefined) out.push(`- line:col: ${ev.line}:${ev.col || 0}`);
        if (ev.reason) out.push(`- reason: \`${truncate(String(ev.reason), 300)}\``);
    }

    return out;
}

// ========== URL 字段(超长截断 + 反查标注) ==========

function urlField(label, url, ctx, jsonlLine) {
    if (!url) return null;
    const s = String(url);
    if (s.length <= ctx.maxUrlLen) {
        return `- ${label}: \`${s}\``;
    }
    // 截断:前 70% + 后 30%(留 1 个省略号)
    const headLen = Math.floor(ctx.maxUrlLen * 0.7);
    const tailLen = Math.max(40, ctx.maxUrlLen - headLen - 1);
    const head = s.slice(0, headLen);
    const tail = s.slice(-tailLen);
    return `- ${label}: \`${head}…${tail}\` *(truncated: ${s.length} → ${ctx.maxUrlLen} chars; full at jsonl#${jsonlLine}, field=${label})*`;
}

// ========== 速览表辅助 ==========

function describeBrief(ev) {
    const t = ev.target;
    const accName = t && t.accessibleName ? `"${truncate(t.accessibleName, 30)}"` : '';
    if (ev.kind === 'interaction') {
        if (ev.type === 'click' || ev.type === 'dblclick' || ev.type === 'contextmenu') {
            return accName || (t && (t.tag + (t.id ? `#${t.id}` : ''))) || '(no target)';
        }
        if (ev.type === 'input' || ev.type === 'change') {
            const field = (t && ((t.attributes && t.attributes.name) || t.id || t.tag)) || '?';
            return String(field);
        }
        if (ev.type === 'submit') {
            return `form ${(t && t.id) ? '#' + t.id : ''}`;
        }
        if (ev.type === 'keydown') {
            return `[${ev.key}]`;
        }
    }
    if (ev.kind === 'network') {
        return `${ev.method || '?'} ${truncate(stripQueryAndHash(ev.requestUrl || ''), 40)}`;
    }
    if (ev.kind === 'navigation') {
        return `→ ${truncate(stripQueryAndHash(ev.to || ev.url || ''), 40)}`;
    }
    if (ev.kind === 'error') {
        return truncate(ev.message || String(ev.reason || ''), 40);
    }
    return '';
}

function stableSelector(target) {
    if (!target || !target.selectors) return '';
    const sel = target.selectors;
    if (sel.testId) {
        const m = String(sel.testId).match(/data-(?:testid|test|cy|qa)="(.+?)"/);
        if (m) return `testId="${m[1]}"`;
    }
    if (sel.role && target.accessibleName) {
        const r = String(sel.role).match(/role=(\w+)/);
        if (r) return `role=${r[1]}[name="${truncate(target.accessibleName, 20)}"]`;
    }
    if (sel.id) return truncate(sel.id, 30);
    if (sel.name) return truncate(sel.name, 30);
    if (sel.ariaLabel) return truncate(sel.ariaLabel, 30);
    if (sel.text) return truncate(sel.text, 30);
    if (sel.css) return truncate(sel.css, 40);
    if (sel.xpath) return truncate('xpath=' + sel.xpath, 40);
    return '(none)';
}

function valueOrUrl(ev) {
    if (ev.kind === 'interaction' && ev.value !== undefined && ev.value !== null) {
        const v = typeof ev.value === 'string' ? truncate(ev.value, 30) : '[obj]';
        return v;
    }
    if (ev.kind === 'network') {
        return `${ev.status !== undefined ? ev.status : 'no-status'}` + (ev.durationMs !== undefined ? ` (${ev.durationMs}ms)` : '');
    }
    if (ev.kind === 'navigation' && ev.to) return truncate(stripQueryAndHash(ev.to), 40);
    if (ev.kind === 'error') return truncate(ev.message || String(ev.reason || ''), 40);
    return '';
}

// ========== 小工具 ==========

function truncate(s, n) {
    s = String(s);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

/** markdown 表格里的危险字符转义 */
function esc(s) {
    return String(s).replace(/\|/g, '\\|').replace(/\n/g, ' ').replace(/`/g, "'");
}

/** 去 query 和 hash,做 URL 覆盖去重 / 速览表简述用 */
function stripQueryAndHash(url) {
    if (!url) return '';
    return String(url).split('?')[0].split('#')[0];
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = (seconds - m * 60).toFixed(0);
    return `${m}m${s}s`;
}
