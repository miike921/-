/**
 * EchoShare 映像中継サーバー
 * - Broadcaster (送信側 iPad) からJPEG フレームを受け取り、
 *   同じルームの Viewer (受信側 iPad) 全員に中継する
 */
const WebSocket = require('ws');
const http = require('http');

const PORT = process.env.PORT || 8080;

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', rooms: rooms.size }));
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('EchoShare 中継サーバー 稼働中');
});

const wss = new WebSocket.Server({ server });

// rooms: Map<roomId, { broadcaster: WS|null, viewers: Set<WS> }>
const rooms = new Map();

function getOrCreateRoom(roomId) {
  if (!rooms.has(roomId)) {
    rooms.set(roomId, { broadcaster: null, viewers: new Set() });
  }
  return rooms.get(roomId);
}

function cleanupRoom(roomId) {
  const room = rooms.get(roomId);
  if (room && !room.broadcaster && room.viewers.size === 0) {
    rooms.delete(roomId);
    console.log(`ルーム削除: ${roomId}`);
  }
}

wss.on('connection', (ws) => {
  ws.isAlive = true;
  ws.roomId = null;
  ws.role = null;

  ws.on('pong', () => { ws.isAlive = true; });

  ws.on('message', (data, isBinary) => {
    if (isBinary) {
      // Broadcaster からの映像フレーム (JPEG バイナリ) → Viewer 全員に中継
      if (ws.role !== 'broadcaster') return;
      const room = rooms.get(ws.roomId);
      if (!room) return;

      room.viewers.forEach(viewer => {
        if (viewer.readyState === WebSocket.OPEN) {
          viewer.send(data, { binary: true });
        }
      });
      return;
    }

    // テキスト (JSON コマンド) の処理
    let msg;
    try {
      msg = JSON.parse(data.toString());
    } catch {
      return;
    }

    switch (msg.type) {
      case 'join':
        handleJoin(ws, msg);
        break;

      case 'ping':
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'pong' }));
        }
        break;
    }
  });

  ws.on('close', () => handleLeave(ws));
  ws.on('error', (err) => console.error('WS エラー:', err.message));
});

function handleJoin(ws, msg) {
  const { roomId, role } = msg;
  if (!roomId || !role) return;

  ws.roomId = roomId;
  ws.role = role;

  const room = getOrCreateRoom(roomId);

  if (role === 'broadcaster') {
    // 既存の Broadcaster を切断
    if (room.broadcaster && room.broadcaster !== ws && room.broadcaster.readyState === WebSocket.OPEN) {
      room.broadcaster.send(JSON.stringify({ type: 'kicked', reason: '別の配信者が接続しました' }));
      room.broadcaster.terminate();
    }
    room.broadcaster = ws;

    // 既存の Viewer に通知
    room.viewers.forEach(v => {
      if (v.readyState === WebSocket.OPEN) {
        v.send(JSON.stringify({ type: 'broadcaster-joined' }));
      }
    });

    ws.send(JSON.stringify({
      type: 'joined',
      role: 'broadcaster',
      roomId,
      viewerCount: room.viewers.size
    }));

    console.log(`[${roomId}] Broadcaster 接続 (視聴者数: ${room.viewers.size})`);

  } else {
    // Viewer として参加
    room.viewers.add(ws);

    // Broadcaster に通知
    if (room.broadcaster && room.broadcaster.readyState === WebSocket.OPEN) {
      room.broadcaster.send(JSON.stringify({
        type: 'viewer-joined',
        count: room.viewers.size
      }));
    }

    ws.send(JSON.stringify({
      type: 'joined',
      role: 'viewer',
      roomId,
      hasBroadcaster: !!room.broadcaster
    }));

    console.log(`[${roomId}] Viewer 接続 (合計: ${room.viewers.size}人)`);
  }
}

function handleLeave(ws) {
  if (!ws.roomId) return;
  const room = rooms.get(ws.roomId);
  if (!room) return;

  if (ws.role === 'broadcaster') {
    room.broadcaster = null;
    // Viewer 全員に配信終了を通知
    room.viewers.forEach(v => {
      if (v.readyState === WebSocket.OPEN) {
        v.send(JSON.stringify({ type: 'stream-ended' }));
      }
    });
    console.log(`[${ws.roomId}] Broadcaster 切断`);
  } else {
    room.viewers.delete(ws);
    if (room.broadcaster && room.broadcaster.readyState === WebSocket.OPEN) {
      room.broadcaster.send(JSON.stringify({
        type: 'viewer-left',
        count: room.viewers.size
      }));
    }
  }

  cleanupRoom(ws.roomId);
}

// 死活監視 (30秒ごと)
const heartbeat = setInterval(() => {
  wss.clients.forEach(ws => {
    if (!ws.isAlive) {
      handleLeave(ws);
      return ws.terminate();
    }
    ws.isAlive = false;
    ws.ping();
  });
}, 30000);

wss.on('close', () => clearInterval(heartbeat));

server.listen(PORT, '0.0.0.0', () => {
  console.log(`EchoShare 中継サーバー起動: ポート ${PORT}`);
  console.log(`ヘルスチェック: http://localhost:${PORT}/health`);
  console.log(`WebSocket: ws://your-server:${PORT}`);
});
