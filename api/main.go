package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/websocket/v2"
	"github.com/redis/go-redis/v9"
)

var ctx = context.Background()
var rdb *redis.Client
var runtimeAccounts = map[int]RuntimeAccount{}
var runtimeAccountsMu sync.RWMutex
var clientSequence atomic.Uint64
var hub *Hub

type Client struct {
	id        string
	conn      *websocket.Conn
	send      chan []byte
	remoteIP  string
	userAgent string
}

type Hub struct {
	clients    map[*Client]bool
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
	mu         sync.RWMutex
}

type ClaimRequest struct {
	UserID string `json:"user_id"`
	Code   string `json:"code"`
	Proxy  string `json:"proxy_url,omitempty"`
}

type RuntimeAccount struct {
	AccountID    int    `json:"account_id"`
	Label        string `json:"label"`
	Username     string `json:"username"`
	CookiesJSON  string `json:"cookies_json"`
	XAccessToken string `json:"x_access_token"`
	UserAgent    string `json:"user_agent"`
	ProxyURL     string `json:"proxy_url"`
	IsEnabled    bool   `json:"is_enabled"`
	IsActive     bool   `json:"is_active"`
}

type AccountEvent struct {
	Type      string `json:"type"`
	AccountID int    `json:"account_id"`
}

type PresencePayload struct {
	ClientID   string `json:"client_id"`
	RemoteIP   string `json:"remote_ip"`
	UserAgent  string `json:"user_agent"`
	Connected  bool   `json:"connected"`
	LastSeenAt string `json:"last_seen_at"`
}

func newHub() *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		broadcast:  make(chan []byte),
		register:   make(chan *Client),
		unregister: make(chan *Client),
	}
}

func (h *Hub) count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

func runHub(h *Hub) {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			if err := syncClientPresence(client, true); err != nil {
				log.Printf("Failed to sync connected client %s: %v", client.id, err)
			}
			go writePump(client, h)
		case client := <-h.unregister:
			h.mu.Lock()
			_, ok := h.clients[client]
			if ok {
				delete(h.clients, client)
			}
			h.mu.Unlock()
			if ok {
				close(client.send)
				if err := syncClientPresence(client, false); err != nil {
					log.Printf("Failed to sync disconnected client %s: %v", client.id, err)
				}
			}
		case message := <-h.broadcast:
			h.mu.RLock()
			activeClients := make([]*Client, 0, len(h.clients))
			for client := range h.clients {
				activeClients = append(activeClients, client)
			}
			h.mu.RUnlock()

			for _, client := range activeClients {
				select {
				case client.send <- message:
				default:
					h.unregister <- client
				}
			}
		}
	}
}

func writePump(client *Client, h *Hub) {
	for message := range client.send {
		if err := client.conn.WriteMessage(websocket.TextMessage, message); err != nil {
			log.Printf("Failed to write to websocket client %s: %v", client.id, err)
			h.unregister <- client
			return
		}
	}
}

func accountRuntimeKey(accountID int) string {
	return "runtime:account:" + strconv.Itoa(accountID)
}

func clientPresenceKey(clientID string) string {
	return "runtime:client:" + clientID
}

func buildPresencePayload(client *Client, connected bool) PresencePayload {
	return PresencePayload{
		ClientID:   client.id,
		RemoteIP:   client.remoteIP,
		UserAgent:  client.userAgent,
		Connected:  connected,
		LastSeenAt: time.Now().UTC().Format(time.RFC3339),
	}
}

func syncClientPresence(client *Client, connected bool) error {
	payload, err := json.Marshal(buildPresencePayload(client, connected))
	if err != nil {
		return err
	}

	key := clientPresenceKey(client.id)
	if connected {
		if err := rdb.Set(ctx, key, payload, 0).Err(); err != nil {
			return err
		}
		if err := rdb.SAdd(ctx, "runtime:clients:connected", client.id).Err(); err != nil {
			return err
		}
	} else {
		if err := rdb.Del(ctx, key).Err(); err != nil {
			return err
		}
		if err := rdb.SRem(ctx, "runtime:clients:connected", client.id).Err(); err != nil {
			return err
		}
	}

	return rdb.Publish(ctx, "events:clients", payload).Err()
}

func broadcastCode(code, source string) {
	if hub == nil {
		return
	}

	message, err := json.Marshal(fiber.Map{
		"type":   "new_code",
		"code":   code,
		"source": source,
	})
	if err != nil {
		log.Printf("Failed to encode broadcast for code %s: %v", code, err)
		return
	}

	hub.broadcast <- message
}

func loadEnabledAccounts() error {
	accountIDs, err := rdb.SMembers(ctx, "runtime:accounts:enabled").Result()
	if err != nil {
		return err
	}

	preloaded := map[int]RuntimeAccount{}
	for _, rawID := range accountIDs {
		accountID, err := strconv.Atoi(rawID)
		if err != nil {
			log.Printf("Skipping invalid runtime account id %q: %v", rawID, err)
			continue
		}

		payload, err := rdb.Get(ctx, accountRuntimeKey(accountID)).Result()
		if err == redis.Nil {
			log.Printf("Runtime account payload missing for account %d", accountID)
			continue
		}
		if err != nil {
			return err
		}

		var account RuntimeAccount
		if err := json.Unmarshal([]byte(payload), &account); err != nil {
			log.Printf("Skipping invalid runtime account payload for account %d: %v", accountID, err)
			continue
		}

		preloaded[accountID] = account
	}

	runtimeAccountsMu.Lock()
	runtimeAccounts = preloaded
	runtimeAccountsMu.Unlock()

	log.Printf("Preloaded %d enabled runtime accounts", len(preloaded))
	return nil
}

func fetchRuntimeAccount(accountID int) (RuntimeAccount, error) {
	payload, err := rdb.Get(ctx, accountRuntimeKey(accountID)).Result()
	if err != nil {
		return RuntimeAccount{}, err
	}

	var account RuntimeAccount
	if err := json.Unmarshal([]byte(payload), &account); err != nil {
		return RuntimeAccount{}, err
	}

	return account, nil
}

func upsertRuntimeAccount(account RuntimeAccount) {
	runtimeAccountsMu.Lock()
	runtimeAccounts[account.AccountID] = account
	runtimeAccountsMu.Unlock()
}

func removeRuntimeAccount(accountID int) {
	runtimeAccountsMu.Lock()
	delete(runtimeAccounts, accountID)
	runtimeAccountsMu.Unlock()
}

func enabledAccountCount() int {
	runtimeAccountsMu.RLock()
	defer runtimeAccountsMu.RUnlock()
	return len(runtimeAccounts)
}

func subscribeAccountEvents() {
	pubsub := rdb.Subscribe(ctx, "events:accounts")
	defer pubsub.Close()

	ch := pubsub.Channel()
	for msg := range ch {
		var event AccountEvent
		if err := json.Unmarshal([]byte(msg.Payload), &event); err != nil {
			log.Printf("Failed to decode account event: %v", err)
			continue
		}

		switch event.Type {
		case "account_enabled", "account_updated":
			account, err := fetchRuntimeAccount(event.AccountID)
			if err == redis.Nil {
				removeRuntimeAccount(event.AccountID)
				log.Printf("Runtime account %d missing during %s event; removed from cache", event.AccountID, event.Type)
				continue
			}
			if err != nil {
				log.Printf("Failed to load runtime account %d: %v", event.AccountID, err)
				continue
			}

			upsertRuntimeAccount(account)
			log.Printf("Runtime account %d cached via %s event", event.AccountID, event.Type)
		case "account_disabled":
			removeRuntimeAccount(event.AccountID)
			log.Printf("Runtime account %d removed via disable event", event.AccountID)
		default:
			log.Printf("Ignoring unknown account event type %q for account %d", event.Type, event.AccountID)
		}
	}
}

func main() {
	// Initialize Redis
	var opts *redis.Options
	redisURL := os.Getenv("REDIS_URL")

	if redisURL != "" {
		// Parse Redis URL
		parsedOpts, err := redis.ParseURL(redisURL)
		if err != nil {
			log.Fatalf("Failed to parse REDIS_URL: %v", err)
		}
		opts = parsedOpts
		log.Println("✅ Using REDIS_URL for connection")
	} else {
		// Fall back to individual config vars
		redisHost := os.Getenv("REDIS_HOST")
		redisPassword := os.Getenv("REDIS_PASSWORD")
		redisPort := os.Getenv("REDIS_PORT")
		if redisPort == "" {
			redisPort = "6379"
		}

		opts = &redis.Options{
			Addr:     redisHost + ":" + redisPort,
			Password: redisPassword,
			DB:       0,
		}
		log.Println("✅ Using individual Redis config vars")
	}

	rdb = redis.NewClient(opts)

	// Test Redis connection
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Fatalf("Failed to connect to Redis: %v", err)
	}
	log.Println("✅ Connected to Redis")

	if err := loadEnabledAccounts(); err != nil {
		log.Fatalf("Failed to preload runtime accounts: %v", err)
	}
	go subscribeAccountEvents()

	hub = newHub()
	go runHub(hub)

	// Initialize Fiber app
	app := fiber.New()

	// Health check with Redis verification
	app.Get("/health", func(c *fiber.Ctx) error {
		start := time.Now()
		err := rdb.Ping(ctx).Err()
		latency := time.Since(start)

		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"status":     "degraded",
				"redis":      "disconnected",
				"latency_ms": latency.Milliseconds(),
				"error":      err.Error(),
			})
		}

		return c.JSON(fiber.Map{
			"status":           "healthy",
			"redis":            "connected",
			"latency_ms":       latency.Milliseconds(),
			"enabled_accounts": enabledAccountCount(),
			"active_clients":   hub.count(),
		})
	})

	app.Get("/ws", websocket.New(func(c *websocket.Conn) {
		clientID := "ws-" + strconv.FormatUint(clientSequence.Add(1), 10)
		client := &Client{
			id:        clientID,
			conn:      c,
			send:      make(chan []byte, 256),
			remoteIP:  c.RemoteAddr().String(),
			userAgent: c.Headers("User-Agent"),
		}

		hub.register <- client

		defer func() {
			hub.unregister <- client
			c.Close()
		}()

		if err := c.WriteJSON(fiber.Map{
			"type":      "connected",
			"client_id": client.id,
			"clients":   hub.count(),
		}); err != nil {
			log.Printf("Failed to send websocket greeting to %s: %v", client.id, err)
			return
		}

		for {
			if _, _, err := c.ReadMessage(); err != nil {
				break
			}
		}
	}))

	// Claim endpoint
	app.Post("/claim", func(c *fiber.Ctx) error {
		var req ClaimRequest
		if err := c.BodyParser(&req); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": "Invalid request body"})
		}

		if req.UserID == "" || req.Code == "" {
			return c.Status(400).JSON(fiber.Map{"error": "Missing user_id or code"})
		}

		// Get queue name from env (default to "claim_queue")
		queueName := os.Getenv("QUEUE_NAME")
		if queueName == "" {
			queueName = "claim_queue"
		}

		// Push to Redis queue
		jobJSON, err := json.Marshal(req)
		if err != nil {
			return c.Status(500).JSON(fiber.Map{"error": "Failed to marshal job"})
		}

		if err := rdb.LPush(ctx, queueName, jobJSON).Err(); err != nil {
			return c.Status(500).JSON(fiber.Map{"error": "Failed to queue job", "details": err.Error()})
		}

		broadcastCode(req.Code, "claim_api")

		return c.JSON(fiber.Map{
			"status":   "queued",
			"message":  "Claim sent to solver grid and broadcast to browser clients",
			"queue":    queueName,
			"clients":  hub.count(),
			"code":     req.Code,
			"broadcast": true,
		})
	})

	app.Post("/broadcast", func(c *fiber.Ctx) error {
		var req struct {
			Code string `json:"code"`
		}
		if err := c.BodyParser(&req); err != nil || req.Code == "" {
			return c.Status(400).JSON(fiber.Map{"error": "Missing code"})
		}

		broadcastCode(req.Code, "manual_broadcast")

		return c.JSON(fiber.Map{
			"status":  "broadcasted",
			"clients": hub.count(),
			"code":    req.Code,
		})
	})

	// Start server
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	log.Printf("API Server starting on port %s", port)
	if err := app.Listen(":" + port); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
