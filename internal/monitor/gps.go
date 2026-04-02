package monitor

import (
	"bufio"
	"io"
	"log"
	"os"
	"sync"
	"time"

	"netinventory/internal/event"

	"github.com/adrianmo/go-nmea"
	"github.com/tarm/serial"
)

// GPSMonitor tracks coordinates from a serial GPS device.
type GPSMonitor struct {
	bus      *event.Bus
	mu       sync.Mutex
	lat, lon float64
	accuracy float64
	lastFix  time.Time
	hasFix   bool
	device   string
	debug    bool
	err      error
	errTip   string
}

func NewGPSMonitor(bus *event.Bus, debug bool) *GPSMonitor {
	return &GPSMonitor{
		bus:   bus,
		debug: debug,
	}
}

func (m *GPSMonitor) Start() {
	device := m.discoverDevice()
	if device == "" {
		log.Println("[GPS] STATUS: GPS NOT FOUND (searched /dev/ttyACM*, /dev/ttyUSB*)")
		return
	}

	m.device = device
	log.Printf("[GPS] SUCCESS: GPS ENABLED / FOUND ON %s", device)

	go m.readLoop(device)
}

func (m *GPSMonitor) discoverDevice() string {
	// Common serial ports for GPS modules
	patterns := []string{
		"/dev/ttyACM0", "/dev/ttyACM1",
		"/dev/ttyUSB0", "/dev/ttyUSB1",
	}

	for _, p := range patterns {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

func (m *GPSMonitor) readLoop(device string) {
	c := &serial.Config{Name: device, Baud: 9600, ReadTimeout: time.Second * 5}
	s, err := serial.OpenPort(c)
	if err != nil {
		m.mu.Lock()
		m.err = err
		if os.IsPermission(err) {
			m.errTip = "Permission denied. Try 'sudo usermod -a -G dialout $USER' and relogin."
		}
		m.mu.Unlock()

		uid := os.Getuid()
		gid := os.Getgid()
		groups, _ := os.Getgroups()
		log.Printf("GPS monitor ERROR: Failed to open %s: %v", device, err)
		log.Printf("Context: UID=%d, GID=%d, Groups=%v", uid, gid, groups)
		if os.IsPermission(err) {
			log.Printf("GPS monitor TIP: %s", m.errTip)
		}
		return
	}
	defer s.Close()

	log.Printf("GPS monitor: Successfully opened %s. Scanning for NMEA data...", device)

	reader := bufio.NewReader(s)
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			if err != io.EOF {
				log.Printf("GPS monitor ERROR: Read error on %s: %v", device, err)
			}
			time.Sleep(1 * time.Second)
			continue
		}

		if m.debug {
			log.Printf("[DEBUG-GPS] RAW: %s", line)
		}

		sentence, err := nmea.Parse(line)
		if err != nil {
			continue
		}

		if sentence.DataType() == nmea.TypeGGA {
			gga := sentence.(nmea.GGA)
			m.mu.Lock()
			wasFix := m.hasFix
			if gga.FixQuality != nmea.Invalid {
				m.lat = gga.Latitude
				m.lon = gga.Longitude
				m.accuracy = gga.HDOP
				m.lastFix = time.Now()
				m.hasFix = true
				if !wasFix {
					log.Printf("[GPS] STATUS: ACQUIRED FIX (%v, %v)", m.lat, m.lon)
				}
			} else {
				m.hasFix = false
				if wasFix {
					log.Println("[GPS] STATUS: LOST FIX")
				}
			}
			m.mu.Unlock()
		}
	}
}

func (m *GPSMonitor) GetFix() map[string]interface{} {
	m.mu.Lock()
	defer m.mu.Unlock()

	res := map[string]interface{}{
		"device": m.device,
	}

	if m.err != nil {
		res["status"] = "error"
		res["error"] = m.err.Error()
		if m.errTip != "" {
			res["error_tip"] = m.errTip
		}
		return res
	}

	if !m.hasFix || time.Since(m.lastFix) > 30*time.Second {
		res["status"] = "no-fix"
		return res
	}

	res["lat"] = m.lat
	res["lon"] = m.lon
	res["accuracy"] = m.accuracy
	res["timestamp"] = m.lastFix.Format(time.RFC3339)
	res["status"] = "fix"
	return res
}
