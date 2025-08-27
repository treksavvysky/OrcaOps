#!/usr/bin/env python3
"""
OrcaOps FastAPI Server Runner

This script starts the OrcaOps FastAPI server for web-based Docker container management.

Usage:
    python run_api.py                    # Start on default port 8000
    python run_api.py --port 3005        # Start on custom port
    python run_api.py --host 0.0.0.0     # Bind to all interfaces
    python run_api.py --reload           # Enable auto-reload for development
"""

import argparse
import sys
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run OrcaOps FastAPI Server")
    parser.add_argument(
        "--host", 
        default="127.0.0.1", 
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--reload", 
        action="store_true", 
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Log level (default: info)"
    )
    
    args = parser.parse_args()
    
    print(f"🐳 Starting OrcaOps FastAPI Server...")
    print(f"🌐 Server will be available at: http://{args.host}:{args.port}")
    print(f"📚 API documentation at: http://{args.host}:{args.port}/docs")
    print(f"🔧 Interactive API explorer at: http://{args.host}:{args.port}/redoc")
    
    try:
        uvicorn.run(
            "main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
