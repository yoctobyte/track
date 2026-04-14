package monitor

import (
	"fmt"
	"os"
	"testing"
	"time"

	"netinventory/internal/event"

	"github.com/tarm/serial"
)

func TestGPSMonitor_GetFix(t *testing.T) {
	bus := event.NewBus()
	m := NewGPSMonitor(bus, false)

	// Test no fix initially
	fix := m.GetFix()
	fmt.Printf("\n>>> [GPS TEST] Initial status (no fix expected): %v\n", fix["status"])
	if fix["status"] != "no-fix" {
		t.Errorf("Expected status 'no-fix', got %v", fix["status"])
	}

	// Test simulated fix
	m.mu.Lock()
	m.lat = 52.5200
	m.lon = 13.4050
	m.accuracy = 1.0
	m.lastFix = time.Now()
	m.hasFix = true
	m.mu.Unlock()

	fix = m.GetFix()
	fmt.Printf(">>> [GPS TEST] Simulated fix: status=%v, lat=%v, lon=%v\n", fix["status"], fix["lat"], fix["lon"])
	if fix["status"] != "fix" {
		t.Errorf("Expected status 'fix', got %v", fix["status"])
	}
	if fix["lat"] != 52.5200 {
		t.Errorf("Expected lat 52.5200, got %v", fix["lat"])
	}

	// Test stale fix
	m.mu.Lock()
	m.lastFix = time.Now().Add(-1 * time.Minute)
	m.mu.Unlock()

	fix = m.GetFix()
	fmt.Printf(">>> [GPS TEST] Stale fix (no fix expected): status=%v\n", fix["status"])
	if fix["status"] != "no-fix" {
		t.Errorf("Expected status 'no-fix' for stale data, got %v", fix["status"])
	}
}

func TestGPSPortConnectivity(t *testing.T) {
	patterns := []string{
		"/dev/ttyACM0", "/dev/ttyACM1",
		"/dev/ttyUSB0", "/dev/ttyUSB1",
	}

	fmt.Println("\n>>> [GPS CONNECTIVITY TEST] Checking common serial ports...")
	for _, p := range patterns {
		fmt.Printf("Checking %s: ", p)
		info, err := os.Stat(p)
		if err != nil {
			if os.IsNotExist(err) {
				fmt.Println("NOT FOUND")
			} else {
				fmt.Printf("ERROR (Stat): %v\n", err)
			}
			continue
		}

		fmt.Printf("FOUND (Mode: %v) -> Attempting to open... ", info.Mode())

		f, err := os.OpenFile(p, os.O_RDWR, 0)
		if err != nil {
			fmt.Printf("FAILED: %v\n", err)
			uid := os.Getuid()
			gid := os.Getgid()
			groups, _ := os.Getgroups()
			fmt.Printf("  Context: UID=%d, GID=%d, Groups=%v\n", uid, gid, groups)
			if os.IsPermission(err) {
				fmt.Println("  TIP: Permission denied. Try 'sudo usermod -a -G dialout $USER'")
			}
		} else {
			fmt.Println("SUCCESS")
			f.Close()
		}
	}
}

func TestGPSLibraryOpen(t *testing.T) {
	p := "/dev/ttyACM0"
	if _, err := os.Stat(p); err != nil {
		t.Skip("Device /dev/ttyACM0 not found, skipping library test")
	}

	fmt.Printf("\n>>> [GPS LIBRARY TEST] Attempting to open %s using tarm/serial...\n", p)
	c := &serial.Config{Name: p, Baud: 9600}
	s, err := serial.OpenPort(c)
	if err != nil {
		fmt.Printf("FAILED: %v\n", err)
		uid := os.Getuid()
		gid := os.Getgid()
		groups, _ := os.Getgroups()
		fmt.Printf("  Context: UID=%d, GID=%d, Groups=%v\n", uid, gid, groups)
	} else {
		fmt.Println("SUCCESS")
		s.Close()
	}
}
