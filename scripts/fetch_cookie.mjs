// 文件简介：从 浏览器调试端口（CDP）导出 admin.example.com 的 cookie 到 cookies.json；登录过期时重跑一次。
import fs from "node:fs";

const list = await (await fetch("http://127.0.0.1:6562/json/list")).json();
const page = list.find(t => t.type === "page" && /admin\.example\.com/.test(t.url)) || list.find(t => t.type === "page");
if (!page) { console.error("no page"); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.addEventListener("message", ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
});
await new Promise(r => ws.addEventListener("open", r));
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });

const all = await send("Network.getAllCookies");
const yj = (all.result?.cookies || []).filter(c => /example\.com$/.test(c.domain));
const out = {};
for (const c of yj) out[c.name] = c.value;
fs.writeFileSync(process.argv[2], JSON.stringify({ cookies: out, domains: yj.map(c => c.domain + " " + c.name), saved_at: new Date().toISOString() }, null, 2), "utf8");
console.log("cookie names:", Object.keys(out).join(","), "| count:", yj.length);
console.log("page:", page.url);
ws.close();
