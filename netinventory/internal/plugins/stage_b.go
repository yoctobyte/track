package plugins

import (
	"bufio"
	"context"
	"os"
	"os/exec"
	"strings"
)

// ARPCachePlugin reads the system ARP cache.
type ARPCachePlugin struct{}

func (p *ARPCachePlugin) Name() string { return "arp_cache" }

func (p *ARPCachePlugin) Run(ctx context.Context) (Result, error) {
	file, err := os.Open("/proc/net/arp")
	if err != nil {
		return Result{}, err
	}
	defer file.Close()

	facts := make(map[string]interface{})
	scanner := bufio.NewScanner(file)
	// Skip header
	if scanner.Scan() {
		for scanner.Scan() {
			fields := strings.Fields(scanner.Text())
			if len(fields) >= 4 {
				facts[fields[0]] = map[string]interface{}{
					"hw_type": fields[1],
					"flags":   fields[2],
					"hw_addr": fields[3],
					"device":  fields[5],
				}
			}
		}
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Facts:   facts,
	}, nil
}

// GatewayPlugin identifies the default gateway MAC and vendor.
type GatewayPlugin struct{}

func (p *GatewayPlugin) Name() string { return "gateway_context" }

func (p *GatewayPlugin) Run(ctx context.Context) (Result, error) {
	// 1. Find default gateway IP via 'ip route'
	out, err := exec.CommandContext(ctx, "ip", "route", "show", "default").Output()
	if err != nil {
		return Result{Name: p.Name(), Success: false, Error: err.Error()}, nil
	}

	fields := strings.Fields(string(out))
	gatewayIP := ""
	for i, f := range fields {
		if f == "via" && i+1 < len(fields) {
			gatewayIP = fields[i+1]
			break
		}
	}

	if gatewayIP == "" {
		return Result{Name: p.Name(), Success: false, Error: "no default gateway found"}, nil
	}

	// 2. Lookup MAC in /proc/net/arp
	gatewayMAC := ""
	arpFile, err := os.Open("/proc/net/arp")
	if err == nil {
		defer arpFile.Close()
		scanner := bufio.NewScanner(arpFile)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.HasPrefix(line, gatewayIP) {
				arpFields := strings.Fields(line)
				if len(arpFields) >= 4 {
					gatewayMAC = arpFields[3]
					break
				}
			}
		}
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Facts: map[string]interface{}{
			"gateway_ip":  gatewayIP,
			"gateway_mac": gatewayMAC,
		},
	}, nil
}
