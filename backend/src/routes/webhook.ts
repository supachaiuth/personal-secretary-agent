import { Request, Response } from 'express';
import { replyToLine } from '../services/line';
import { callAI } from '../services/ai';

// LINE event types
interface LineMessageEvent {
  type: string;
  message: {
    type: string;
    text: string;
  };
  replyToken: string;
  source: {
    userId: string;
  };
}

interface LineWebhookBody {
  events: LineMessageEvent[];
}

/**
 * POST /webhook
 * LINE Messaging API webhook endpoint
 * 
 * Handles incoming LINE events and replies to users
 */
export async function handleWebhook(req: Request, res: Response): Promise<void> {
  console.log('[Webhook] Received webhook request');
  console.log('[Webhook] Headers:', req.headers);
  
  const body = req.body as LineWebhookBody;
  
  // Validate request body
  if (!body || !body.events || !Array.isArray(body.events)) {
    console.warn('[Webhook] Invalid request body - no events found');
    res.status(200).json({ status: 'ok', message: 'No events to process' });
    return;
  }
  
  console.log(`[Webhook] Processing ${body.events.length} event(s)`);
  
  // Process each event
  for (const event of body.events) {
    try {
      await processEvent(event);
    } catch (error) {
      console.error('[Webhook] Error processing event:', error);
      // Continue processing other events even if one fails
    }
  }
  
  // Return 200 quickly as required by LINE API
  res.status(200).json({ status: 'ok' });
}

/**
 * Process a single LINE event
 */
async function processEvent(event: LineMessageEvent): Promise<void> {
  console.log('[Webhook] Event type:', event.type);
  
  // Only handle message events
  if (event.type !== 'message') {
    console.log('[Webhook] Skipping non-message event');
    return;
  }
  
  // Only handle text messages
  if (event.message.type !== 'text') {
    console.log('[Webhook] Skipping non-text message');
    return;
  }
  
  const userMessage = event.message.text;
  const replyToken = event.replyToken;
  const userId = event.source.userId;
  
  console.log(`[Webhook] User ${userId} said: "${userMessage}"`);
  
  // Call AI to process the message
  console.log('[Webhook] Calling AI service...');
  const aiResponse = await callAI(userMessage);
  console.log('[Webhook] AI response:', aiResponse);
  
  // Send reply to LINE
  console.log('[Webhook] Sending reply to LINE...');
  const sent = await replyToLine(replyToken, aiResponse);
  
  if (sent) {
    console.log('[Webhook] Reply sent successfully');
  } else {
    console.error('[Webhook] Failed to send reply');
  }
}
