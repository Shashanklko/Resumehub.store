"""
main.py — Master Application Entry Point
========================================
Handles shared initialization and concurrent startup of:
1. Flask Web API [WEB]
2. Telegram Bot [BOT]
"""

import os
import sys
import logging
import threading
import signal
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

# Configure Global Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("MASTER")

# 1. Path setup
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# 2. Shared Initialization (Load .env and setup AI)
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
    logger.info(f"✅ Loaded local configuration from {env_path}")
else:
    logger.warning("⚠️ No .env file found. Reading credentials from system environment variables.")

# Configure Gemini globally
gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if gemini_key:
    # Set environment variable explicitly for libraries that check it
    os.environ["GOOGLE_API_KEY"] = gemini_key
    os.environ["GEMINI_API_KEY"] = gemini_key
    genai.configure(api_key=gemini_key)
    logger.info("✅ Gemini API configured successfully.")
else:
    logger.error("❌ CRITICAL ERROR: No Gemini API Key found in .env or environment!")
    sys.exit(1)

# 3. Import Application Modules (after shared setup is complete)
from bot import init_bot, run_bot
from web_app import app, set_bot_application

def start_web():
    """Starts the Flask server."""
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"[WEB] Starting Web Server on port {port}...")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def handle_singleton():
    """Ensures only one instance of the master stack is running."""
    pid_file = BASE_DIR / "main.pid"
    
    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                old_pid = int(f.read().strip())
            
            # Try to kill the old process (cross-platform logic)
            if old_pid != os.getpid():
                logger.info(f"🔄 Detected zombie process (PID: {old_pid}). Terminating...")
                if sys.platform == "win32":
                    os.system(f"taskkill /F /PID {old_pid} 2>NUL")
                else:
                    os.kill(old_pid, signal.SIGTERM)
        except Exception as e:
            logger.warning(f"⚠️ Could not kill old process: {e}")
            
    # Write current PID
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    return pid_file

async def run_production():
    """Starts the application stack using Webhooks (Optimized for Render)."""
    application = init_bot()
    if not application: return
    
    # 1. Inject application into web server
    set_bot_application(application)
    
    # 2. Set Webhook URL
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = os.getenv("RENDER_EXTERNAL_URL")
    if not base_url:
        logger.error("❌ RENDER_EXTERNAL_URL not set! Cannot enable webhooks.")
        return
    
    webhook_url = f"{base_url.rstrip('/')}/telegram/webhook/{token}"
    logger.info(f"[BOT] Setting webhook to: {webhook_url}")
    
    # Clear any old polling sessions and set new webhook
    await application.initialize()
    await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    await application.start()
    
    logger.info("🚀 [BOT] Webhook mode active. Entry point: /telegram/webhook/")
    
    # 3. Start Web Server in main thread (Production usually uses Gunicorn, but this works for development/render)
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"[WEB] Starting Master Web Server on port {port}...")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def main():
    """Main entry point with environment-aware startup."""
    pid_file = handle_singleton()
    is_render = os.getenv("RENDER") == "true"
    
    try:
        if is_render:
            logger.info("🌍 [RENDER] Production environment detected. Initializing Webhook Stack...")
            import asyncio
            asyncio.run(run_production())
        else:
            logger.info("💻 [LOCAL] Development environment detected. Initializing Polling Stack...")
            # Traditional threaded startup for local development
            web_thread = threading.Thread(target=start_web, daemon=True)
            web_thread.start()
            
            logger.info("[BOT] Starting Telegram Bot polling loop...")
            run_bot()
            
    except KeyboardInterrupt:
        logger.info("🛑 User requested shutdown.")
    except Exception as e:
        logger.error(f"❌ [MASTER] Fatal Error: {e}", exc_info=True)
    finally:
        if pid_file.exists():
            os.remove(pid_file)
        logger.info("👋 Master stack shutdown complete.")

if __name__ == "__main__":
    main()
