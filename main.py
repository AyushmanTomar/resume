import sys
import os
import threading
import webview
import subprocess
import socket
import time
import logging
from logging.handlers import RotatingFileHandler
import tempfile
import atexit
import signal

# Setup logging to file
log_dir = os.path.join(tempfile.gettempdir(), 'resume_analyzer_logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'resume_analyzer.log')

logger = logging.getLogger('resume_analyzer')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Console handler for debugging
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(formatter)
logger.addHandler(console)

def find_free_port():
    """Find a free port to run the Streamlit app on"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]

def is_port_in_use(port):
    """Check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def run_streamlit(script_path, port):
    """Run the Streamlit app"""
    logger.info(f"Starting Streamlit server on port {port}...")
    
    # Determine if we're running in a PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # We're running in a PyInstaller bundle
        base_dir = sys._MEIPASS
    else:
        # We're running in a normal Python environment
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    script_path = os.path.join(base_dir, script_path)
    
    # Check if the script exists
    if not os.path.exists(script_path):
        logger.error(f"Script not found: {script_path}")
        return None
    
    try:
        # Create a process for streamlit run
        streamlit_cmd = [
            sys.executable,
            "-m", "streamlit", 
            "run", 
            script_path,
            "--server.port", str(port),
            "--server.headless", "true",
            "--server.enableCORS", "false",
            "--server.enableXsrfProtection", "false",
            "--browser.serverAddress", "localhost",
            "--browser.gatherUsageStats", "false",
            "--server.address", "localhost"
        ]
        
        # Redirect stdout and stderr to prevent console windows on Windows
        if os.name == 'nt':  # Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                streamlit_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )
        else:  # Unix/Linux/Mac
            process = subprocess.Popen(
                streamlit_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        
        # Store the process object to terminate it later
        return process
    
    except Exception as e:
        logger.error(f"Error starting Streamlit: {e}")
        return None

def wait_for_streamlit(port, timeout=30):
    """Wait for Streamlit to start"""
    logger.info(f"Waiting for Streamlit to be ready on port {port}...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) == 0:
                    # Wait additional time for the server to fully initialize
                    time.sleep(2)
                    logger.info("Streamlit server is ready!")
                    return True
        except Exception:
            pass
        
        time.sleep(0.5)
    
    logger.error("Timeout waiting for Streamlit to start")
    return False

def cleanup(streamlit_process):
    """Clean up resources when the app is closed"""
    if streamlit_process:
        logger.info("Terminating Streamlit process...")
        try:
            if os.name == 'nt':  # Windows
                # On Windows, we need to use taskkill to ensure child processes are also terminated
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(streamlit_process.pid)])
            else:
                # On Unix systems, terminate the process group
                streamlit_process.terminate()
                streamlit_process.wait(timeout=5)
                
        except Exception as e:
            logger.error(f"Error terminating Streamlit process: {e}")
            # Force kill if terminate fails
            try:
                streamlit_process.kill()
            except:
                pass

def main():
    logger.info("Starting Resume Job Match Analyzer...")
    
    # Find a free port
    port = find_free_port()
    streamlit_process = None
    
    try:
        # Start Streamlit in a separate process
        streamlit_process = run_streamlit("app.py", port)
        
        if not streamlit_process:
            logger.error("Failed to start Streamlit")
            return
        
        # Register cleanup function
        atexit.register(lambda: cleanup(streamlit_process))
        
        # Wait for Streamlit to start
        if not wait_for_streamlit(port):
            logger.error("Streamlit failed to start in time")
            cleanup(streamlit_process)
            return
        
        # Create the window
        webview.create_window(
            title="Resume Job Match Analyzer",
            url=f"http://localhost:{port}",
            width=1200,
            height=800,
            min_size=(800, 600),
            confirm_close=True
        )
        
        # Start the webview
        webview.start(gui="edgechromium" if os.name == 'nt' else "gtk")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        # Clean up
        cleanup(streamlit_process)
        logger.info("Application closed")

if __name__ == '__main__':
    # Handle SIGINT (Ctrl+C) gracefully
    def signal_handler(sig, frame):
        logger.info("Received interrupt signal, shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    main()