package plugins

import (
	"context"
	"io"
	"net/http"
	"os/exec"
	"time"
)

// ExternalIPPlugin fetches the public IP address.
type ExternalIPPlugin struct{}

func (p *ExternalIPPlugin) Name() string { return "external_ip" }

func (p *ExternalIPPlugin) Run(ctx context.Context) (Result, error) {
	client := &http.Client{Timeout: 5 * time.Second}
	req, _ := http.NewRequestWithContext(ctx, "GET", "https://api.ipify.org", nil)

	resp, err := client.Do(req)
	if err != nil {
		return Result{Name: p.Name(), Success: false, Error: err.Error()}, nil
	}
	defer resp.Body.Close()

	ip, err := io.ReadAll(resp.Body)
	if err != nil {
		return Result{Name: p.Name(), Success: false, Error: err.Error()}, nil
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Facts:   map[string]interface{}{"ip": string(ip)},
	}, nil
}

// TraceroutePlugin wraps tracepath to map the network path.
type TraceroutePlugin struct {
	Target string
}

func (p *TraceroutePlugin) Name() string { return "traceroute" }

func (p *TraceroutePlugin) Run(ctx context.Context) (Result, error) {
	target := p.Target
	if target == "" {
		target = "1.1.1.1"
	}

	cmd := exec.CommandContext(ctx, "tracepath", "-n", "-m", "10", target)
	out, err := cmd.CombinedOutput()

	return Result{
		Name:    p.Name(),
		Success: err == nil,
		Raw:     string(out),
		Facts:   map[string]interface{}{"target": target},
	}, nil
}
