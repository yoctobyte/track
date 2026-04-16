package plugins

import (
	"context"
	"fmt"
	"net"
	"os/exec"
	"time"
)

// PingPlugin pings the default gateway.
type PingPlugin struct {
	Target string
}

func (p *PingPlugin) Name() string { return "ping_gateway" }

func (p *PingPlugin) Run(ctx context.Context) (Result, error) {
	if p.Target == "" {
		return Result{Name: p.Name(), Success: false, Error: "no target specified"}, nil
	}

	cmd := exec.CommandContext(ctx, "ping", "-c", "3", "-W", "2", p.Target)
	out, err := cmd.CombinedOutput()

	success := err == nil
	return Result{
		Name:    p.Name(),
		Success: success,
		Raw:     string(out),
		Facts:   map[string]interface{}{"target": p.Target},
	}, nil
}

// DNSResolvePlugin tests DNS resolution.
type DNSResolvePlugin struct{}

func (p *DNSResolvePlugin) Name() string { return "dns_test" }

func (p *DNSResolvePlugin) Run(ctx context.Context) (Result, error) {
	start := time.Now()
	_, err := net.DefaultResolver.LookupHost(ctx, "google.com")
	duration := time.Since(start).String()

	return Result{
		Name:    p.Name(),
		Success: err == nil,
		Facts: map[string]interface{}{
			"test_domain": "google.com",
			"latency":     duration,
			"error_msg":   fmt.Sprintf("%v", err),
		},
	}, nil
}
