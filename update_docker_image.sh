docker pull tofuconnected/markov-chain-bot:latest
docker stop markov-chain-bot
docker rm markov-chain-bot
docker run --name markov-chain-bot -d -p 8081:8080 \
    --env TELEGRAM_BOT_TOKEN="YOUR_TOKEN_LOL" \
    -v /volume1/Dev/markov-chain-bot/markov_data.db:/app/markov_data.db:rw \
    tofuconnected/markov-chain-bot:latest