package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/websocket/v2"
	"github.com/redis/go-redis/v9"
)

var ctx = context.Background()
var rdb *redis.Client

// Client represents a WebSocket browser client
type Client struct {
	conn *websocket.Conn
	send chan []byte
}

// Hub manages active browser connections
type Hub struct {
	clients    map[*Client]bool
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
}

var hub *Hub

func runHub(h *Hub) {
	for {
		select {
		case client := <-h.register:
			h.clients[client] = true
		case client := <-h.unregister:
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
		case message := <-h.broadcast:
			for client := range h.clients {
				select {
				case client.send <- message:
				default:
					// Client is slow, drop message to prevent blocking
					close(client.send)
					delete(h.clients, client)
				}
			}
		}
	}
}

type ClaimRequest struct {
	UserID string `json:"user_id"`
	Code   string `json:"code"`
	Proxy  string `json:"proxy_url,omitempty"`
}

func main() {
	// Initialize Redis
	redisHost := os.Getenv("REDIS_HOST")
	redisPassword := os.Getenv("REDIS_PASSWORD")
	redisPort := os.Getenv("REDIS_PORT")
	if redisPort == "" {
		redisPort = "6379"
	}

	rdb = redis.NewClient(&redis.Options{
		Addr:     redisHost + ":" + redisPort,
		Password: redisPassword,
		DB:       0,
	})

	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Fatalf("Failed to connect to Redis: %v", err)
	}
	log.Println("✅ Connected to Redis")

	// Initialize Hub
	hub = &Hub{
		clients:    make(map[*Client]bool),
		broadcast:  make(chan []byte),
		register:   make(chan *Client),
		unregister: make(chan *Client),
	}
	go runHub(hub)

	// Initialize Fiber app
	app := fiber.New()

	// Health check
	app.Get("/health", func(c *fiber.Ctx) error {
		start := time.Now()
		err := rdb.Ping(ctx).Err()
		latency := time.Since(start)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{"status": "degraded", "error": err.Error()})
		}
		return c.JSON(fiber.Map{"status": "healthy", "latency_ms": latency.Milliseconds(), "active_clients": len(hub.clients)})
	})

	// 1. WEBSOCKET ENDPOINT (For Browser Clients)
	// Browsers connect here to receive codes instantly
	app.Get("/ws", websocket.New(func(c *websocket.Conn) {
		client := &Client{
			conn: c,
			send: make(chan []byte, 256),
		}

		hub.register <- client

		defer func() {
			hub.unregister <- client
			c.Close()
		}()

		// Send current active count
		c.WriteJSON(fiber.Map{"type": "connected", "clients": len(hub.clients)})

		for {
			_, _, err := c.ReadMessage()
			if err != nil {
				break
			}
			// Browsers don't send codes, they only receive them.
			// If you need them to send "claim success" back, handle it here.
		}
	}))

	// 2. HTTP POST ENDPOINT (For API Clients / Your Scripts)
	// You send a code here, and it goes to YOUR Solver
	app.Post("/claim", func(c *fiber.Ctx) error {
		var req ClaimRequest
		if err := c.BodyParser(&req); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": "Invalid request"})
		}

		if req.UserID == "" || req.Code == "" {
			return c.Status(400).JSON(fiber.Map{"error": "Missing user_id or code"})
		}

		log.Printf("🔔 API Request: Code=%s (Routing to Solver)", req.Code)

		// Route to Solver Queue
		queueName := os.Getenv("QUEUE_NAME")
		if queueName == "" {
			queueName = "claim_queue"
		}

		jobJSON, _ := json.Marshal(req)
		if err := rdb.LPush(ctx, queueName, jobJSON).Err(); err != nil {
			return c.Status(500).JSON(fiber.Map{"error": "Failed to queue job"})
		}

		return c.JSON(fiber.Map{
			"status":  "queued",
			"message": "Code sent to server solver",
			"queue":   queueName,
		})
	})

	// 3. BROADCAST ENDPOINT (Optional: Manual trigger to send to browsers)
	// If you want to manually push a code to browsers without claiming it yourself
	app.Post("/broadcast", func(c *fiber.Ctx) error {
		var req struct {
			Code string `json:"code"`
		}
		if err := c.BodyParser(&req); err != nil || req.Code == "" {
			return c.Status(400).JSON(fiber.Map{"error": "Missing code"})
		}

		log.Printf("📡 Manual Broadcast: Code=%s (Sending to %d browsers)", req.Code, len(hub.clients))

		msg := map[string]string{
			"type": "new_code",
			"code": req.Code,
			"source": "manual_broadcast",
		}
		jsonMsg, _ := json.Marshal(msg)
		hub.broadcast <- jsonMsg

		return c.JSON(fiber.Map{"status": "broadcasted", "clients": len(hub.clients)})
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	log.Printf("API Server starting on port %s (Hybrid: HTTP→Solver, WS→Browser)", port)
	if err := app.Listen(":" + port); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}