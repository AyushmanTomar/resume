import os
import platform
import subprocess
import sys

def build_executable():
    """Build the executable using PyInstaller"""
    print("Starting build process...")
    
    # Determine the system
    system = platform.system()
    print(f"Building for {system} platform")
    
    # Base PyInstaller command
    pyinstaller_command = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--name", "Resume Job Match Analyzer",
        "--add-data", f"app.py{os.pathsep}.",
        "--hidden-import", "streamlit",
        "--hidden-import", "PyGithub",
        "--hidden-import", "google.generativeai",
        "--hidden-import", "pywebview",
    ]
    
    # Platform-specific settings
    if system == "Windows":
        pyinstaller_command.extend([
            "--icon", "icon.ico",
            "--noconsole",
            "--add-binary", f"{sys.prefix}/Lib/site-packages/streamlit/runtime/static{os.pathsep}streamlit/runtime/static"
        ])
    elif system == "Darwin":  # macOS
        pyinstaller_command.extend([
            "--icon", "icon.icns",
            "--add-binary", f"{sys.prefix}/Lib/site-packages/streamlit/runtime/static{os.pathsep}streamlit/runtime/static",
            "--osx-bundle-identifier", "com.yourcompany.resumeanalyzer"
        ])
    elif system == "Linux":
        pyinstaller_command.extend([
            "--icon", "icon.png",
            "--add-binary", f"{sys.prefix}/Lib/site-packages/streamlit/runtime/static{os.pathsep}streamlit/runtime/static"
        ])
    
    # Add the main script
    pyinstaller_command.append("main.py")
    
    try:
        # Run PyInstaller
        result = subprocess.run(pyinstaller_command, check=True, capture_output=True, text=True)
        print("Build successful!")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("Build failed!")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    build_executable()