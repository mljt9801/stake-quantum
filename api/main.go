package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/redis/go-redis/v9"
)

var ctx = context.Background()
var rdb *redis.Client

type ClaimRequest struct {
	UserID string `json:"user_id"`
	Code   string `json:"code"`
	Proxy  string `json:"proxy_url,omitempty"`
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
			"status":     "healthy",
			"redis":      "connected",
			"latency_ms": latency.Milliseconds(),
		})
	})

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

		return c.JSON(fiber.Map{
			"status":  "queued",
			"message": "Claim sent to solver grid",
			"queue":   queueName,
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