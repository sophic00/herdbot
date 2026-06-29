# Use the official Pixi image as the build and runtime base
FROM prefixdev/pixi:latest

WORKDIR /app

# Copy configuration files first to cache dependency installation
COPY pixi.toml pixi.lock ./

# Install project dependencies
RUN pixi install --locked

# Copy the rest of the application files
COPY . .

# Set up the default start command
CMD ["pixi", "run", "start-bot"]
