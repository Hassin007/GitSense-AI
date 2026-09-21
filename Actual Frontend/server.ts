import express from 'express';
import path from 'path';
import { createServer as createViteServer } from 'vite';
import { GoogleGenAI } from '@google/genai';
import { INITIAL_USER, INITIAL_REPOS, INITIAL_COMMITS, MOCK_COMMIT_DETAILS } from './src/mockData';
import { ConnectedRepo, CommitListItem, CommitDetail, ConnectRepoRequest } from './src/types';

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // In-memory state for runtime operations
  let connectedRepos: ConnectedRepo[] = [...INITIAL_REPOS];
  let commitFeed: CommitListItem[] = [...INITIAL_COMMITS];
  let commitDetails: Record<number, CommitDetail> = { ...MOCK_COMMIT_DETAILS };

  // Lazy Gemini AI initialization
  const getAI = () => {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) return null;
    return new GoogleGenAI({ apiKey });
  };

  // Helper auth check middleware / token parser
  const parseToken = (req: express.Request) => {
    const queryToken = req.query.token as string;
    const authHeader = req.headers.authorization;
    return queryToken || (authHeader ? authHeader.replace('Bearer ', '') : null);
  };

  // ==========================================
  // FASTAPI BACKEND API PROXY
  // ==========================================
  app.use('/api', async (req, res) => {
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
    const targetUrl = `${backendUrl}${req.url}`;

    if (req.url.startsWith('/auth/login')) {
      res.redirect(targetUrl);
      return;
    }

    try {
      const headers: Record<string, string> = {};
      for (const [key, value] of Object.entries(req.headers)) {
        if (key.toLowerCase() !== 'host' && typeof value === 'string') {
          headers[key] = value;
        }
      }

      const fetchOptions: RequestInit = {
        method: req.method,
        headers,
        redirect: 'follow',
      };

      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method) && req.body && Object.keys(req.body).length > 0) {
        fetchOptions.body = JSON.stringify(req.body);
      }

      const response = await fetch(targetUrl, fetchOptions);
      res.status(response.status);

      response.headers.forEach((val, key) => {
        if (key.toLowerCase() !== 'transfer-encoding') {
          res.setHeader(key, val);
        }
      });

      const data = await response.arrayBuffer();
      res.send(Buffer.from(data));
    } catch (err) {
      console.error(`Proxy error connecting to backend (${targetUrl}):`, err);
      res.status(502).json({ error: 'Failed to connect to FastAPI backend server.' });
    }
  });

  // ==========================================
  // VITE SERVING MIDDLEWARE
  // ==========================================
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`GitSense AI Server running at http://0.0.0.0:${PORT}`);
  });
}

startServer();
