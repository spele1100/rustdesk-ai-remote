#!/usr/bin/env node
/**
 * AI Remote Desktop Controller
 *
 * Connects to a remote agent, captures screenshots, sends them to a vision model,
 * and executes actions in a loop until the task is complete.
 *
 * Usage:
 *   node index.js --agent http://target:5800 --task "Open Chrome and go to google.com"
 *   node index.js --agent ws://target:5800/stream --task "Click the Start button"
 */

import { WebSocket } from 'ws';
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import { join } from 'path';

// ── Configuration ───────────────────────────────────────────────────

const CONFIG = {
  agentUrl: process.env.AGENT_URL || 'http://localhost:5800',
  visionApiUrl: process.env.VISION_API_URL || 'https://api.z.ai/api/coding/paas/v4/chat/completions',
  visionApiKey: process.env.VISION_API_KEY || process.env.ZAI_API_KEY || '',
  visionModel: process.env.VISION_MODEL || 'glm-4.6v',
  maxSteps: parseInt(process.env.MAX_STEPS || '30'),
  screenshotDelay: parseInt(process.env.SCREENSHOT_DELAY || '1000'),
  debugDir: process.env.DEBUG_DIR || './debug-screenshots',
};

// ── Parse CLI args ──────────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  let task = '';
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--task' && args[i + 1]) { task = args[++i]; }
    else if (args[i] === '--agent' && args[i + 1]) { CONFIG.agentUrl = args[++i]; }
    else if (args[i] === '--steps' && args[i + 1]) { CONFIG.maxSteps = parseInt(args[++i]); }
    else if (args[i] === '--delay' && args[i + 1]) { CONFIG.screenshotDelay = parseInt(args[++i]); }
    else if (args[i] === '--model' && args[i + 1]) { CONFIG.visionModel = args[++i]; }
    else if (args[i] === '--help') {
      console.log(`Usage: node index.js [options]
  --task <prompt>      Task description for the AI to execute
  --agent <url>        Agent URL (default: http://localhost:5800)
  --steps <n>          Max steps (default: 30)
  --delay <ms>         Delay between steps (default: 1000)
  --model <name>       Vision model name (default: glm-4.6v)
  --help               Show this help`);
      process.exit(0);
    }
  }
  return task || 'Describe what you see on the screen.';
}

// ── Vision Model API ────────────────────────────────────────────────

async function analyzeScreenshot(imageBase64, task, history) {
  const systemPrompt = `You are an AI desktop assistant. You control a remote computer by analyzing screenshots and deciding actions.

Available actions:
- {"action": "click", "x": <int>, "y": <int>, "button": "left"|"right"|"middle"}
- {"action": "double_click", "x": <int>, "y": <int>}
- {"action": "type", "text": "<string>"}
- {"action": "key_press", "keys": ["ctrl", "c"]}  (keys: ctrl, alt, shift, meta/win/cmd, enter, tab, escape, backspace, delete, f1-f12, space, up/down/left/right, or single chars)
- {"action": "scroll", "x": <int>, "y": <int>, "delta": <int>}  (negative = scroll down, positive = scroll up)
- {"action": "drag", "from": [x1, y1], "to": [x2, y2]}
- {"action": "wait", "ms": <int>}
- {"action": "done", "reason": "<explanation>"}  — when task is complete

Rules:
1. Respond with EXACTLY ONE action as JSON. No other text.
2. Use absolute pixel coordinates based on the screenshot.
3. If the task is complete, respond with {"action": "done", "reason": "..."}.
4. If something goes wrong or you're stuck, use {"action": "done", "reason": "stuck: ..."}.
5. Be precise with coordinates. Look carefully at the screenshot.
6. Think step by step about what you need to do.`;

  // Build messages with history
  const messages = [
    { role: 'system', content: systemPrompt },
  ];

  // Add history (last N interactions)
  for (const entry of history.slice(-10)) {
    messages.push({
      role: 'user',
      content: [
        { type: 'image_url', image_url: { url: `data:image/png;base64,${entry.screenshot}` } },
      ],
    });
    messages.push({
      role: 'assistant',
      content: entry.action,
    });
  }

  // Current screenshot + task
  messages.push({
    role: 'user',
    content: [
      { type: 'text', text: `Current task: ${task}\n\nWhat action should I take next? Respond with exactly one JSON action.` },
      { type: 'image_url', image_url: { url: `data:image/png;base64,${imageBase64}` } },
    ],
  });

  const response = await fetch(CONFIG.visionApiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(CONFIG.visionApiKey ? { 'Authorization': `Bearer ${CONFIG.visionApiKey}` } : {}),
    },
    body: JSON.stringify({
      model: CONFIG.visionModel,
      messages,
      max_tokens: 256,
      temperature: 0.1,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Vision API error ${response.status}: ${text}`);
  }

  const data = await response.json();
  const content = data.choices?.[0]?.message?.content || '';

  return { content, usage: data.usage };
}

// ── Parse action from model response ────────────────────────────────

function parseAction(text) {
  // Try to extract JSON from the response
  const jsonMatch = text.match(/\{[^{}]*\}/s);
  if (!jsonMatch) {
    throw new Error(`No JSON action found in model response: ${text}`);
  }

  let action;
  try {
    action = JSON.parse(jsonMatch[0]);
  } catch (e) {
    throw new Error(`Failed to parse action JSON: ${jsonMatch[0]}`);
  }

  if (!action.action) {
    throw new Error(`Action missing "action" field: ${JSON.stringify(action)}`);
  }

  return action;
}

// ── Agent Communication ─────────────────────────────────────────────

async function takeScreenshot() {
  const url = `${CONFIG.agentUrl}/screenshot`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Screenshot failed: ${response.status}`);
  const buffer = await response.arrayBuffer();
  return Buffer.from(buffer).toString('base64');
}

async function sendCommand(action) {
  if (action.action === 'done') return { ok: true, message: action.reason };

  const url = `${CONFIG.agentUrl}/input`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(action),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Command failed ${response.status}: ${text}`);
  }

  return await response.json();
}

// ── Kill Switch Check ───────────────────────────────────────────────

let killed = false;

function checkKillSwitch(result) {
  if (result?.message === 'EMERGENCY_STOP' || result?.message?.includes('EMERGENCY_STOP')) {
    console.log('\n🚨 EMERGENCY STOP received from agent! Shutting down immediately.');
    killed = true;
    return true;
  }
  return false;
}

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n⏹  Ctrl+C received. Stopping...');
  killed = true;
});
process.on('SIGTERM', () => {
  killed = true;
});

// ── Debug helpers ───────────────────────────────────────────────────

function saveDebugScreenshot(base64, step) {
  if (!existsSync(CONFIG.debugDir)) mkdirSync(CONFIG.debugDir, { recursive: true });
  const path = join(CONFIG.debugDir, `step-${String(step).padStart(3, '0')}.png`);
  writeFileSync(path, Buffer.from(base64, 'base64'));
  return path;
}

// ── Main Loop ───────────────────────────────────────────────────────

async function main() {
  const task = parseArgs();

  console.log('═'.repeat(60));
  console.log('🤖 AI Remote Desktop Controller');
  console.log('═'.repeat(60));
  console.log(`  Agent:    ${CONFIG.agentUrl}`);
  console.log(`  Vision:   ${CONFIG.visionModel}`);
  console.log(`  Task:     ${task}`);
  console.log(`  Max steps: ${CONFIG.maxSteps}`);
  console.log('═'.repeat(60));
  console.log();

  // Check agent health
  try {
    const health = await fetch(`${CONFIG.agentUrl}/health`);
    if (!health.ok) throw new Error(`Health check failed: ${health.status}`);
    console.log('✅ Agent is online');
  } catch (e) {
    console.error(`❌ Cannot reach agent at ${CONFIG.agentUrl}: ${e.message}`);
    console.error('   Make sure the agent is running on the target machine.');
    process.exit(1);
  }

  const history = [];
  let totalTokens = 0;

  for (let step = 1; step <= CONFIG.maxSteps && !killed; step++) {
    console.log(`\n── Step ${step}/${CONFIG.maxSteps} ──`);

    // 1. Take screenshot
    console.log('📸 Taking screenshot...');
    let screenshot;
    try {
      screenshot = await takeScreenshot();
    } catch (e) {
      console.error(`❌ Screenshot failed: ${e.message}`);
      console.log('   Retrying in 2s...');
      await sleep(2000);
      try {
        screenshot = await takeScreenshot();
      } catch (e2) {
        console.error(`❌ Screenshot failed again: ${e2.message}`);
        break;
      }
    }

    // Debug save
    const debugPath = saveDebugScreenshot(screenshot, step);
    console.log(`   Saved: ${debugPath}`);

    // 2. Analyze with vision model
    console.log('🧠 Analyzing with vision model...');
    let visionResult;
    try {
      visionResult = await analyzeScreenshot(screenshot, task, history);
    } catch (e) {
      console.error(`❌ Vision API error: ${e.message}`);
      break;
    }

    totalTokens += visionResult.usage?.total_tokens || 0;
    console.log(`   Model: ${visionResult.content.substring(0, 100)}...`);

    // 3. Parse action
    let action;
    try {
      action = parseAction(visionResult.content);
    } catch (e) {
      console.error(`❌ Parse error: ${e.message}`);
      console.log('   Raw response:', visionResult.content);
      break;
    }

    console.log(`   Action: ${JSON.stringify(action)}`);

    // Check if done
    if (action.action === 'done') {
      console.log(`\n✅ Task complete! Reason: ${action.reason || 'N/A'}`);
      break;
    }

    // Save to history
    history.push({ screenshot, action: JSON.stringify(action) });

    // 4. Execute action
    console.log('⚡ Executing action...');
    let result;
    try {
      result = await sendCommand(action);
    } catch (e) {
      console.error(`❌ Execution error: ${e.message}`);
      break;
    }

    console.log(`   Result: ${result.ok ? '✅' : '❌'} ${result.message || ''}`);

    // Kill switch
    if (checkKillSwitch(result)) break;

    // 5. Wait before next step
    await sleep(CONFIG.screenshotDelay);
  }

  console.log('\n═'.repeat(60));
  if (killed) {
    console.log('🚫 Session terminated (kill switch or user interrupt)');
  } else {
    console.log('🏁 Session ended');
  }
  console.log(`   Steps: ${Math.min(history.length + 1, CONFIG.maxSteps)}`);
  console.log(`   Tokens used: ~${totalTokens}`);
  console.log('═'.repeat(60));
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

main().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
