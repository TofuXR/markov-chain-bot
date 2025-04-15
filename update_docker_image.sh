docker pull tofuconnected/markov-chain-bot:latest
docker stop markov-chain-bot
docker rm markov-chain-bot
docker run --name markov-chain-bot -d -p 8080:8080 --env BOT_TOKEN="7560852017:AAHGpd1m3GzctkynO363YxuEzmFdI8x6Z7s" -v /volume1/Dev/markov-chain-bot/markov_data.db:/app/markov_data.db:rw tofuconnected/markov-chain-bot:latest