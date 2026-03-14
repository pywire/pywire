import sys
import os
import time

# Add src to path
sys.path.insert(0, os.path.join(os.getcwd(), "src"))

from pywire_shell import App

def main():
    html_path = os.path.abspath("verify.html")
    url = f"file://{html_path}"
    
    app = App(
        title="Interactivity Verification",
        url=url,
        width=1024,
        height=768
    )
    
    print(f"Starting verification app with {url}")
    app.start()

if __name__ == "__main__":
    main()
