package plugins

import (
	"context"
	"net"
	"os"
)

// InterfacePlugin gathers basic interface details.
type InterfacePlugin struct{}

func (p *InterfacePlugin) Name() string { return "interface_details" }

func (p *InterfacePlugin) Run(ctx context.Context) (Result, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return Result{}, err
	}

	facts := make(map[string]interface{})
	for _, i := range interfaces {
		addrs, _ := i.Addrs()
		facts[i.Name] = map[string]interface{}{
			"index":        i.Index,
			"mtu":          i.MTU,
			"hardware_addr": i.HardwareAddr.String(),
			"flags":        i.Flags.String(),
			"addresses":    addrs,
		}
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Facts:   facts,
	}, nil
}

// IPPlugin gathers IP and routing information from system files.
type IPPlugin struct{}

func (p *IPPlugin) Name() string { return "ip_routes" }

func (p *IPPlugin) Run(ctx context.Context) (Result, error) {
	// For Phase 1, we'll just read /proc/net/route as a raw artifact example
	routeData, err := os.ReadFile("/proc/net/route")
	if err != nil {
		return Result{}, err
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Raw:     string(routeData),
		Facts:   map[string]interface{}{"source": "/proc/net/route"},
	}, nil
}
