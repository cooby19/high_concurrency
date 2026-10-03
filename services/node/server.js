'use strict';
const http = require('node:http');
const cluster = require('node:cluster');
const workers = Number(process.env.WORKERS || 1);
if (cluster.isPrimary && workers > 1) {
  for (let i = 0; i < workers; i++) cluster.fork();
  cluster.on('exit', () => process.exit(1));
} else {
  const agent = new http.Agent({keepAlive: true, maxSockets: Infinity});
  const integer = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;
  const keys = (v, names) => v && !Array.isArray(v) && typeof v === 'object' && Object.keys(v).sort().join() === names;
  const json = (res, code, data) => {res.writeHead(code, {'Content-Type':'application/json'}); res.end(JSON.stringify(data));};
  const error = (res, code, message) => json(res, code, {error: message});
  http.createServer(async (req, res) => {
    const [path, query] = req.url.split('?');
    const methods = {'/health':'GET','/io':'GET','/json':'POST','/cpu':'POST'};
    if (!(path in methods)) return error(res, 404, 'not_found');
    if (req.method !== methods[path]) return error(res, 405, 'method_not_allowed');
    if (query) return error(res, 400, 'invalid_request');
    if (path === '/health') return json(res, 200, {status:'ok'});
    if (path === '/io') {
      let finished = false;
      const fail = () => {if (!finished) {finished = true; error(res, 502, 'downstream_error');}};
      const downstream = http.get(process.env.DOWNSTREAM_URL, {agent, headers:{'Accept-Encoding':'identity'}}, response => {
        let size = 0; const chunks = [];
        response.on('data', chunk => {size += chunk.length; if (size > 1024) downstream.destroy(); else chunks.push(chunk);});
        response.on('error', fail);
        response.on('end', () => {
          const data = Buffer.concat(chunks);
          if (response.statusCode !== 200 || data.length !== 1024 || !data.equals(Buffer.alloc(1024, 'x'))) return fail();
          if (!finished) {finished = true; res.writeHead(200, {'Content-Type':'application/octet-stream'}); res.end(data);}
        });
      });
      const timer = setTimeout(() => {downstream.destroy(); fail();}, 1500);
      downstream.on('error', fail); res.on('finish', () => clearTimeout(timer));
      return;
    }
    if ((req.headers['content-type'] || '').split(';')[0].trim().toLowerCase() !== 'application/json') return error(res, 415, 'unsupported_media_type');
    let size = 0; const chunks = [];
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 4096) {error(res, 413, 'payload_too_large'); return;}
        chunks.push(chunk);
      }
      const raw = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true}).decode(Buffer.concat(chunks));
      const data = JSON.parse(raw);
      if (path === '/cpu') {
        if (!keys(data, 'seed') || !integer(data.seed, 0, 4294967295)) throw Error();
        let x = data.seed;
        for (let i = 0; i < 100000; i++) x = (Math.imul(1664525, x) + 1013904223) >>> 0;
        return json(res, 200, {result:x});
      }
      if (!keys(data, 'id,name,padding,values') || !integer(data.id, 0, 4294967295) || typeof data.name !== 'string' || !/^[A-Za-z0-9_]{1,32}$/.test(data.name) || !Array.isArray(data.values) || data.values.length !== 16 || !data.values.every(v => integer(v, -1000, 1000)) || data.padding !== 'x'.repeat(896)) throw Error();
      json(res, 200, {id:data.id, name:data.name, sum:data.values.reduce((a,b) => a+b, 0), padding:data.padding});
    } catch {if (!res.headersSent) error(res, 400, 'invalid_request');}
  }).listen(Number(process.env.PORT || 8080), '0.0.0.0');
}
