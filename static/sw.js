/* SpendLog-Analytics Service Worker（8.4）
   - 静态资源：cache-first，离线可用
   - 页面/导航：network-first（保证拿到最新），失败回退缓存
   - /api/*：直接走网络，绝不缓存（保持数据实时）
   版本号递增即触发缓存更新。 */
const CACHE = 'spendlog-v4';
const CORE = [
  '/',
  '/index.html',
  '/style.css',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

self.addEventListener('install', ev => {
  ev.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(CORE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', ev => {
  ev.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', ev => {
  const url = ev.request.url;
  if (ev.request.method !== 'GET') return;
  if (url.includes('/api/')) return; // API 永不缓存
  const req = ev.request;

  // 导航（页面）与静态资源策略
  if (req.mode === 'navigate') {
    ev.respondWith(
      fetch(req)
        .then(res => { cachePut('/index.html', res.clone()); return res; })
        .catch(() => caches.match('/index.html'))
    );
    return;
  }
  ev.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(
      res => { if (res && res.status === 200) cachePut(req, res.clone()); return res; }
    ))
  );
});

function cachePut(key, res) {
  caches.open(CACHE).then(c => c.put(key, res));
}