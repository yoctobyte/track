package monitor

import (
	"log"
	"os/exec"
	"strings"
	"time"

	"netinventory/internal/event"
)

// WiFiMonitor polls for WiFi connection changes.
type WiFiMonitor struct {
	bus      *event.Bus
	lastSSID string
}

func NewWiFiMonitor(bus *event.Bus) *WiFiMonitor {
	return &WiFiMonitor{bus: bus}
}

func (m *WiFiMonitor) Start() {
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		for range ticker.C {
			ssid := m.getCurrentSSID()
			if ssid != m.lastSSID {
				eventType := event.TypeWiFiConnect
				if ssid == "" {
					eventType = event.TypeWiFiDisconnect
				}

				m.bus.Publish(event.Event{
					Type:      eventType,
					Timestamp: time.Now().Unix(),
					Source:    "wifi_monitor",
					Metadata: map[string]interface{}{
						"ssid": ssid,
						"prev": m.lastSSID,
					},
				})
				m.lastSSID = ssid
			}
		}
	}()
	log.Println("WiFi monitor started (polling)")
}

func (m *WiFiMonitor) getCurrentSSID() string {
	// Simple nmcli check for Phase 1
	out, err := exec.Command("nmcli", "-t", "-f", "active,ssid", "dev", "wifi").Output()
	if err != nil {
		return ""
	}

	lines := strings.Split(string(out), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "yes:") {
			return strings.TrimPrefix(line, "yes:")
		}
	}
	return ""
}
