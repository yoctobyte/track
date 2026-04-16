package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"netinventory/internal/collect"
	"netinventory/internal/event"
	"netinventory/internal/monitor"
)

func main() {
	debugGPS := flag.Bool("debug-gps", false, "Enable raw GPS data logging")
	flag.Parse()

	log.Println("Starting NetInventory Collector...")

	// 1. Initialize Foundation
	bus := event.NewBus()
	store, err := collect.NewStore("data/snapshots")
	if err != nil {
		log.Fatalf("Failed to initialize store: %v", err)
	}

	// 2. Initialize Monitors
	nlMonitor := monitor.NewNetlinkMonitor(bus)
	wfMonitor := monitor.NewWiFiMonitor(bus)
	gpsMonitor := monitor.NewGPSMonitor(bus, *debugGPS)

	// 3. Initialize Orchestrator
	engine := collect.NewOrchestrator(bus, store, gpsMonitor)

	// 4. Start everything
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := nlMonitor.Start(); err != nil {
		log.Printf("Warning: Netlink monitor failed to start: %v", err)
	}
	wfMonitor.Start()
	gpsMonitor.Start()
	engine.Start(ctx)

	// 5. Wait for interrupt
	log.Println("NetInventory Collector running.")

	// Manual trigger for first run to verify it works
	bus.Publish(event.Event{
		Type:      event.TypeManual,
		Timestamp: int64(0),
		Source:    "main",
	})

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig

	log.Println("Shutting down...")
}
