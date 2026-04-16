package collect

import (
	"encoding/json"
	"fmt"
	"testing"

	"netinventory/internal/event"
	"netinventory/internal/monitor"
	"netinventory/internal/plugins"
)

func TestGathering_FullRun(t *testing.T) {
	bus := event.NewBus()

	// Create a dummy store that doesn't actually save to disk for the test
	// or use a temporary directory.
	tmpDir := t.TempDir()
	store, _ := NewStore(tmpDir)

	gps := monitor.NewGPSMonitor(bus, false)

	// Pre-populate GPS with a fix so it shows up in gathering
	// Since monitor.GPSMonitor fields are unexported except through methods,
	// we rely on the provider interface used in plugins.

	o := NewOrchestrator(bus, store, gps)

	// Define a custom playbook for testing to avoid external dependencies like Ping/DNS if they are slow
	testPlaybook := []plugins.Plugin{
		&plugins.InterfacePlugin{},
		&plugins.GPSPlugin{Provider: gps},
		plugins.NewScriptPlugin("echo_test", "echo", `{"status": "captured", "value": 42}`),
	}

	fmt.Println("\n>>> [TEST] Starting gathering simulation...")

	// Directly execute the playbook logic similar to takeSnapshot
	results := o.runner.Run(testPlaybook)

	fmt.Println(">>> [TEST] Captured Facts:")
	for _, res := range results {
		factJSON, _ := json.MarshalIndent(res.Facts, "  ", "  ")
		fmt.Printf("Plugin: %s\n  Success: %v\n  Facts: %s\n", res.Name, res.Success, string(factJSON))
	}

	if len(results) == 0 {
		t.Error("No results returned from playbook")
	}
}
