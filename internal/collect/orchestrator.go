package collect

import (
	"context"
	"log"
	"time"

	"netinventory/internal/event"
	"netinventory/internal/monitor"
	"netinventory/internal/plugins"

	"github.com/google/uuid"
)

// Orchestrator coordinates events, snapshots, and playbooks.
type Orchestrator struct {
	bus      *event.Bus
	store    *Store
	runner   *plugins.Runner
	gps      *monitor.GPSMonitor
	cooldown map[event.Type]time.Time
}

func NewOrchestrator(bus *event.Bus, store *Store, gps *monitor.GPSMonitor) *Orchestrator {
	return &Orchestrator{
		bus:      bus,
		store:    store,
		runner:   plugins.NewRunner(30 * time.Second),
		gps:      gps,
		cooldown: make(map[event.Type]time.Time),
	}
}

func (o *Orchestrator) Start(ctx context.Context) {
	events := o.bus.Subscribe()

	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case e := <-events:
				if o.shouldTrigger(e) {
					go o.takeSnapshot(e)
				}
			}
		}
	}()
	log.Println("Orchestrator started")
}

func (o *Orchestrator) shouldTrigger(e event.Event) bool {
	// Simple debounce logic for Phase 1
	last, ok := o.cooldown[e.Type]
	if ok && time.Since(last) < 10*time.Second {
		return false
	}
	o.cooldown[e.Type] = time.Now()

	// Only trigger snapshots on specific event types for now
	switch e.Type {
	case event.TypeInterfaceUp, event.TypeIPChange, event.TypeWiFiConnect, event.TypeManual:
		return true
	default:
		return false
	}
}

func (o *Orchestrator) takeSnapshot(trigger event.Event) {
	log.Printf("Triggering snapshot due to event: %s", trigger.Type)

	snap := &Snapshot{
		ID:        uuid.New().String(),
		Timestamp: time.Now(),
		Triggers:  []event.Event{trigger},
		Data:      make(map[string]interface{}),
	}

	// Define Phase 1 Playbook
	playbook := []plugins.Plugin{
		&plugins.InterfacePlugin{},
		&plugins.IPPlugin{},
		&plugins.ARPCachePlugin{},
		&plugins.GatewayPlugin{},
		&plugins.DNSResolvePlugin{},
		&plugins.GPSPlugin{Provider: o.gps},
		&plugins.ExternalIPPlugin{},
		&plugins.WiFiPlugin{},
		&plugins.TraceroutePlugin{Target: "1.1.1.1"},
		plugins.NewScriptPlugin("python_test", "python3", "-c", "import json; print(json.dumps({'status': 'Python is ready', 'engine': 'experimental'}))"),
		// Note: Ping target would be derived from IP/Route facts in a more advanced version
	}

	log.Printf("Starting playbook execution for snapshot %s", snap.ID)
	results := o.runner.Run(playbook)
	log.Printf("Playbook execution finished for snapshot %s", snap.ID)

	facts := make(map[string]interface{})
	for _, res := range results {
		facts[res.Name] = res
	}
	snap.Data = facts
	snap.Outcome = "success"

	// Derive NetID
	netCtx := NetworkContext{
		InterfaceType: "unknown",
	}

	// Basic Extraction Logic (Phase 3 Prep)
	// We look for specific facts from known plugins.
	// Improved Extraction Logic
	if res, ok := facts["gateway_context"].(plugins.Result); ok && res.Success {
		if ip, ok := res.Facts["gateway_ip"].(string); ok {
			netCtx.GatewayIP = ip
		}
		if mac, ok := res.Facts["gateway_mac"].(string); ok {
			netCtx.GatewayMAC = mac
		}
	}
	if res, ok := facts["external_ip"].(plugins.Result); ok && res.Success {
		if ip, ok := res.Facts["ip"].(string); ok {
			netCtx.ExternalIP = ip
		}
	}
	if res, ok := facts["wifi_info"].(plugins.Result); ok && res.Success {
		if ssid, ok := res.Facts["ssid"].(string); ok {
			netCtx.SSID = ssid
		}
		if bssid, ok := res.Facts["bssid"].(string); ok {
			netCtx.BSSID = bssid
		}
		netCtx.InterfaceType = "wifi"
	}
	// Extract SSID/BSSID from InterfacePlugin if available (omitted for brevity)

	snap.NetID = DeriveNetID(netCtx)

	log.Printf("Saving snapshot %s to store", snap.ID)
	if err := o.store.Save(snap); err != nil {
		log.Printf("Failed to save snapshot: %v", err)
	} else {
		log.Printf("Snapshot %s saved successfully", snap.ID)
		if err := o.store.SetActive(snap.NetID); err != nil {
			log.Printf("Failed to update active network: %v", err)
		}
	}
}
