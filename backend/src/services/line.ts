import axios from 'axios';

// LINE API endpoint for replying to messages
const LINE_REPLY_URL = 'https://api.line.me/v2/bot/message/reply';

/**
 * Send a reply message to LINE user
 * @param replyToken - The reply token from the incoming event
 * @param message - The message text to send back
 * @returns Promise<boolean> - true if successful, false otherwise
 */
export async function replyToLine(replyToken: string, message: string): Promise<boolean> {
  const channelAccessToken = process.env.LINE_CHANNEL_ACCESS_TOKEN;

  if (!channelAccessToken) {
    console.error('[LINE Service] ERROR: LINE_CHANNEL_ACCESS_TOKEN not configured');
    return false;
  }

  try {
    const response = await axios.post(
      LINE_REPLY_URL,
      {
        replyToken: replyToken,
        messages: [
          {
            type: 'text',
            text: message,
          },
        ],
      },
      {
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${channelAccessToken}`,
        },
        timeout: 10000,
      }
    );

    if (response.status === 200) {
      console.log('[LINE Service] Reply sent successfully');
      return true;
    }

    console.warn('[LINE Service] Unexpected response status:', response.status);
    return false;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      console.error('[LINE Service] Axios error:', error.message);
      if (error.response) {
        console.error('[LINE Service] Response data:', error.response.data);
      }
    } else {
      console.error('[LINE Service] Unknown error:', error);
    }
    return false;
  }
}

/**
 * Verify LINE signature from webhook request
 * @param body - Raw request body as string
 * @param signature - X-Line-Signature header value
 * @returns boolean - true if signature is valid
 */
export function verifyLineSignature(body: string, signature: string): boolean {
  const channelSecret = process.env.LINE_CHANNEL_SECRET;
  
  if (!channelSecret) {
    console.warn('[LINE Service] LINE_CHANNEL_SECRET not configured - skipping signature verification');
    return true; // In production, should return false
  }

  const crypto = require('crypto');
  const hash = crypto
    .createHmac('sha256', channelSecret)
    .update(body, 'utf8')
    .digest('base64');

  return hash === signature;
}
