# Simple test Docker image - Basic web server
FROM alpine:latest

# Install Python and curl
RUN apk add --no-cache python3 py3-pip curl

# Set working directory
WORKDIR /app

# Create a simple Python web server
RUN echo 'import http.server; import socketserver; import os
PORT = 8080
Handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Server running at port {PORT}")
    httpd.serve_forever()' > simple_server.py

# Create a simple index.html
RUN echo '<h1>OrcaOps Test Container</h1><p>Simple test successful!</p>' > index.html

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

# Start the server
CMD ["python3", "simple_server.py"]
