import express, { Request, Response } from 'express';
import dotenv from 'dotenv';
import { handleWebhook } from './routes/webhook';

// Load environment variables
dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());

// Health check endpoint
app.get('/health', (req: Request, res: Response) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    service: 'personal-secretary-backend'
  });
});

// Webhook endpoint for LINE Messaging API
app.post('/webhook', handleWebhook);

// Root endpoint
app.get('/', (req: Request, res: Response) => {
  res.json({
    message: 'Personal Secretary Backend API',
    version: '1.0.0',
    endpoints: {
      health: 'GET /health',
      webhook: 'POST /webhook'
    }
  });
});

// Error handling middleware
app.use((err: Error, req: Request, res: Response, next: Function) => {
  console.error('[Error] Unhandled error:', err);
  res.status(500).json({
    error: 'Internal server error',
    message: err.message
  });
});

// Start server
app.listen(PORT, () => {
  console.log('========================================');
  console.log('Personal Secretary Backend Started');
  console.log('========================================');
  console.log(`Server running on port ${PORT}`);
  console.log(`Health check: http://localhost:${PORT}/health`);
  console.log(`Webhook URL: http://localhost:${PORT}/webhook`);
  console.log('========================================');
  
  // Check required environment variables
  if (!process.env.LINE_CHANNEL_ACCESS_TOKEN) {
    console.warn('WARNING: LINE_CHANNEL_ACCESS_TOKEN not set in .env');
  }
});

export default app;
