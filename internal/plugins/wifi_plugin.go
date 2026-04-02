package plugins

import (
	"context"
	"os/exec"
	"strings"
)

// WiFiPlugin captures current wireless connection details.
type WiFiPlugin struct{}

func (p *WiFiPlugin) Name() string { return "wifi_info" }

func (p *WiFiPlugin) Run(ctx context.Context) (Result, error) {
	// Using nmcli for Linux-based SSID/BSSID discovery
	out, err := exec.CommandContext(ctx, "nmcli", "-t", "-f", "active,ssid,bssid,signal", "dev", "wifi").Output()
	if err != nil {
		return Result{Name: p.Name(), Success: false, Error: err.Error()}, nil
	}

	facts := make(map[string]interface{})
	lines := strings.Split(string(out), "\n")
	for _, line := range lines {
		parts := parseNmcliLine(line)
		if len(parts) > 0 && parts[0] == "yes" {
			if len(parts) >= 4 {
				facts["ssid"] = parts[1]
				facts["bssid"] = parts[2]
				facts["signal"] = parts[3]
				break
			}
		}
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Facts:   facts,
	}, nil
}

// parseNmcliLine handles escaped colons (\:) in nmcli -t output.
func parseNmcliLine(line string) []string {
	var parts []string
	var current strings.Builder
	escaped := false
	for _, r := range line {
		if escaped {
			current.WriteRune(r)
			escaped = false
			continue
		}
		if r == '\\' {
			escaped = true
			continue
		}
		if r == ':' {
			parts = append(parts, current.String())
			current.Reset()
			continue
		}
		current.WriteRune(r)
	}
	parts = append(parts, current.String())
	return parts
}
