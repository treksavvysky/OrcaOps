#!/usr/bin/env python3
"""
Advanced Flask Web API for Docker testing
Provides system info, health checks, and logging endpoints
"""

import os
import time
import json
import logging
import psutil
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from threading import Thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/app.log'),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Global stats
start_time = time.time()
request_count = 0

def log_request_info():
    """Middleware to log request information"""
    global request_count
    request_count += 1
    logger.info(f"Request #{request_count}: {request.method} {request.path} from {request.remote_addr}")

@app.before_request
def before_request():
    log_request_info()

@app.route('/')
def home():
    """Home page with system information"""
    uptime = time.time() - start_time
    return render_template('index.html', 
                         uptime=round(uptime, 2),
                         requests=request_count,
                         hostname=os.uname().nodename)

@app.route('/health')
def health_check():
    """Health check endpoint for Docker HEALTHCHECK"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime_seconds': round(time.time() - start_time, 2)
    })

@app.route('/api/system')
def system_info():
    """Return detailed system information"""
    try:
        return jsonify({
            'hostname': os.uname().nodename,
            'platform': os.uname().sysname,
            'architecture': os.uname().machine,
            'cpu_count': os.cpu_count(),
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory': {
                'total': psutil.virtual_memory().total,
                'available': psutil.virtual_memory().available,
                'percent': psutil.virtual_memory().percent
            },
            'disk': {
                'total': psutil.disk_usage('/').total,
                'free': psutil.disk_usage('/').free,
                'percent': psutil.disk_usage('/').percent
            },
            'uptime_seconds': round(time.time() - start_time, 2),
            'request_count': request_count,
            'environment_vars': {k: v for k, v in os.environ.items() if not k.startswith('_')},
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return jsonify({'error': 'Failed to get system info'}), 500

@app.route('/api/stress/<int:duration>')
def stress_test(duration):
    """CPU stress test endpoint"""
    if duration > 30:
        return jsonify({'error': 'Duration too long, max 30 seconds'}), 400
    
    def cpu_stress():
        end_time = time.time() + duration
        while time.time() < end_time:
            pass
    
    logger.info(f"Starting {duration}s CPU stress test")
    thread = Thread(target=cpu_stress)
    thread.start()
    
    return jsonify({
        'message': f'CPU stress test started for {duration} seconds',
        'duration': duration,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/logs')
def get_logs():
    """Return recent application logs"""
    try:
        with open('/app/logs/app.log', 'r') as f:
            logs = f.readlines()
        
        # Return last 50 lines
        recent_logs = logs[-50:] if len(logs) > 50 else logs
        
        return jsonify({
            'logs': [log.strip() for log in recent_logs],
            'total_lines': len(logs),
            'showing_lines': len(recent_logs)
        })
    except FileNotFoundError:
        return jsonify({'error': 'Log file not found'}), 404
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return jsonify({'error': 'Failed to read logs'}), 500

if __name__ == '__main__':
    logger.info("Starting Advanced Flask Test API")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"User ID: {os.getuid()}")
    
    # Run the Flask development server
    app.run(host='0.0.0.0', port=8080, debug=False)
