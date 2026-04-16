package monitor

import (
	"fmt"
	"log"
	"time"

	"netinventory/internal/event"

	"github.com/vishvananda/netlink"
)

// NetlinkMonitor listens for kernel network events.
type NetlinkMonitor struct {
	bus *event.Bus
}

// NewNetlinkMonitor creates a new monitor.
func NewNetlinkMonitor(bus *event.Bus) *NetlinkMonitor {
	return &NetlinkMonitor{bus: bus}
}

// Start begins listening for Netlink events.
func (m *NetlinkMonitor) Start() error {
	ch := make(chan netlink.AddrUpdate)
	done := make(chan struct{})
	if err := netlink.AddrSubscribe(ch, done); err != nil {
		return fmt.Errorf("failed to subscribe to address updates: %w", err)
	}

	linkCh := make(chan netlink.LinkUpdate)
	if err := netlink.LinkSubscribe(linkCh, done); err != nil {
		return fmt.Errorf("failed to subscribe to link updates: %w", err)
	}

	routeCh := make(chan netlink.RouteUpdate)
	if err := netlink.RouteSubscribe(routeCh, done); err != nil {
		return fmt.Errorf("failed to subscribe to route updates: %w", err)
	}

	go func() {
		for {
			select {
			case addr := <-ch:
				m.bus.Publish(event.Event{
					Type:      event.TypeIPChange,
					Timestamp: time.Now().Unix(),
					Source:    "netlink",
					Metadata: map[string]interface{}{
						"address": addr.LinkAddress.String(),
						"index":   addr.LinkIndex,
						"new":     addr.NewAddr,
					},
				})
			case link := <-linkCh:
				eventType := event.TypeInterfaceUp
				if link.Header.Type == 0 { // Placeholder check, need to refine based on actual flags
					// Simplified for MVP
				}
				
				m.bus.Publish(event.Event{
					Type:      eventType,
					Timestamp: time.Now().Unix(),
					Source:    "netlink",
					Metadata: map[string]interface{}{
						"link_name": link.Attrs().Name,
						"index":     link.Attrs().Index,
						"flags":     link.Attrs().Flags.String(),
					},
				})
			case route := <-routeCh:
				m.bus.Publish(event.Event{
					Type:      event.TypeRouteChange,
					Timestamp: time.Now().Unix(),
					Source:    "netlink",
					Metadata: map[string]interface{}{
						"dst": route.Dst.String(),
						"gw":  route.Gw.String(),
					},
				})
			}
		}
	}()

	log.Println("Netlink monitor started")
	return nil
}
