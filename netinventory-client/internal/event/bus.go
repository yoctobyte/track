package event

import (
	"sync"
)

// Type represents the kind of event that occurred.
type Type string

const (
	TypeInterfaceUp   Type = "interface_up"
	TypeInterfaceDown Type = "interface_down"
	TypeIPChange     Type = "ip_change"
	TypeRouteChange  Type = "route_change"
	TypeWiFiConnect  Type = "wifi_connect"
	TypeWiFiDisconnect Type = "wifi_disconnect"
	TypeGPSFix       Type = "gps_fix"
	TypeGPSMove      Type = "gps_move"
	TypeManual       Type = "manual_capture"
	TypeJobFinished  Type = "job_finished"
)

// Event represents a single noteworthy occurrence in the system.
type Event struct {
	Type      Type
	Timestamp int64
	Source    string
	Metadata  map[string]interface{}
}

// Bus handles event distribution.
type Bus struct {
	mu          sync.RWMutex
	subscribers []chan Event
}

// NewBus creates a new event bus.
func NewBus() *Bus {
	return &Bus{
		subscribers: make([]chan Event, 0),
	}
}

// Subscribe adds a new listener for events.
func (b *Bus) Subscribe() chan Event {
	b.mu.Lock()
	defer b.mu.Unlock()

	ch := make(chan Event, 100)
	b.subscribers = append(b.subscribers, ch)
	return ch
}

// Publish broadcasts an event to all subscribers.
func (b *Bus) Publish(e Event) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	for _, ch := range b.subscribers {
		// Non-blocking publish to avoid slow subscribers stalling the bus.
		select {
		case ch <- e:
		default:
			// Optionally log dropped events if a channel is full.
		}
	}
}
