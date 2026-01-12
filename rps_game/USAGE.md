# Использование с параметрами командной строки

## Запуск серверов на разных портах

Теперь вы можете запускать несколько экземпляров серверов на разных портах для тестирования leader election.

### ORM Service

```bash
# Запуск на порту по умолчанию (из config.json)
python -m orm_service.orm_server

# Запуск на кастомном порту
python -m orm_service.orm_server --port 50053

# Запуск с кастомным Consul
python -m orm_service.orm_server --port 50053 --consul-host localhost --consul-port 8500
```

**Параметры:**
- `--port` - Порт для ORM сервера
- `--consul-host` - Адрес Consul
- `--consul-port` - Порт Consul

### Game Server

```bash
# Запуск на порту по умолчанию (из config.json)
python -m game_server.game_server

# Запуск на кастомном порту
python -m game_server.game_server --port 50052

# Запуск с кастомным Consul
python -m game_server.game_server --port 50052 --consul-host localhost --consul-port 8500
```

**Параметры:**
- `--port` - Порт для Game сервера
- `--consul-host` - Адрес Consul
- `--consul-port` - Порт Consul

## Примеры использования

### Тестирование Leader Election для ORM

Откройте 3 терминала:

**Терминал 1 (ORM Leader #1):**
```bash
python -m orm_service.orm_server --port 50052
```

**Терминал 2 (ORM Follower #1):**
```bash
python -m orm_service.orm_server --port 50053
```

**Терминал 3 (ORM Follower #2):**
```bash
python -m orm_service.orm_server --port 50054
```

Один из них станет лидером и запишет свой URL в Consul KV `service/rps-orm/leader`.

Проверьте в Consul UI (http://localhost:8500):
- Services → rps-orm-service (должно быть 3 экземпляра)
- Key/Value → service/rps-orm/leader (адрес текущего лидера)

Остановите лидера (Ctrl+C) и наблюдайте, как один из followers автоматически станет новым лидером.

### Тестирование Leader Election для Game Server

Откройте 3 терминала:

**Терминал 1 (Game Leader #1):**
```bash
python -m game_server.game_server --port 50051
```

**Терминал 2 (Game Follower #1):**
```bash
python -m game_server.game_server --port 50052
```

**Терминал 3 (Game Follower #2):**
```bash
python -m game_server.game_server --port 50055
```

Проверьте в Consul UI:
- Services → rps-game-service (должно быть 3 экземпляра)
- Key/Value → service/rps-game/leader (адрес текущего лидера)

Клиенты автоматически подключатся к лидеру и переподключатся при его смене.

### Полная конфигурация с несколькими серверами

```bash
# Терминал 1: Consul + DB
docker-compose up -d

# Терминал 2: ORM Server #1
python -m orm_service.orm_server --port 50052

# Терминал 3: ORM Server #2
python -m orm_service.orm_server --port 50053

# Терминал 4: Game Server #1
python -m game_server.game_server --port 50051

# Терминал 5: Game Server #2
python -m game_server.game_server --port 50055

# Терминал 6: Client #1
python -m client.rps_client

# Терминал 7: Client #2
python -m client.rps_client
```

## Мониторинг

### Проверка текущего лидера ORM

```bash
curl http://localhost:8500/v1/kv/service/rps-orm/leader?raw
```

### Проверка текущего лидера Game Server

```bash
curl http://localhost:8500/v1/kv/service/rps-game/leader?raw
```

### Просмотр всех зарегистрированных сервисов

```bash
curl http://localhost:8500/v1/catalog/services
```

### Просмотр экземпляров ORM сервиса

```bash
curl http://localhost:8500/v1/catalog/service/rps-orm-service
```

### Просмотр экземпляров Game сервиса

```bash
curl http://localhost:8500/v1/catalog/service/rps-game-service
```

## Сценарии тестирования

### Сценарий 1: Failover ORM сервера

1. Запустите 2 ORM сервера на разных портах
2. Запустите Game Server (он подключится к ORM лидеру)
3. Запустите клиент и создайте игру
4. Остановите ORM лидера
5. Наблюдайте:
   - Новый ORM лидер выбирается автоматически
   - Game Server переподключается к новому ORM лидеру
   - Игра продолжается без потери данных

### Сценарий 2: Failover Game сервера

1. Запустите ORM сервер
2. Запустите 2 Game сервера на разных портах
3. Запустите клиент (он подключится к Game лидеру)
4. Создайте игру
5. Остановите Game лидера
6. Наблюдайте:
   - Новый Game лидер выбирается автоматически
   - Клиент автоматически переподключается к новому лидеру
   - Игровая сессия восстанавливается из БД

### Сценарий 3: Множественные клиенты

1. Запустите инфраструктуру (Consul, DB, ORM, Game Server)
2. Запустите 4 клиента
3. Создайте 2 игровые комнаты
4. Играйте одновременно в обеих комнатах
5. Остановите Game лидера
6. Наблюдайте, как все клиенты переподключаются к новому лидеру

## Отладка

### Включение подробных логов

Добавьте в начало файлов серверов:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Проверка портов

```bash
# Windows
netstat -ano | findstr :50051

# Linux/Mac
lsof -i :50051
```

### Очистка Consul KV

```bash
# Удалить ключ лидера ORM
curl -X DELETE http://localhost:8500/v1/kv/service/rps-orm/leader

# Удалить ключ лидера Game
curl -X DELETE http://localhost:8500/v1/kv/service/rps-game/leader
```

### Перезапуск всех сервисов

```bash
# Остановить все Docker контейнеры
docker-compose down

# Запустить заново
docker-compose up -d

# Подождать 5 секунд
# Запустить серверы с нужными портами
```
