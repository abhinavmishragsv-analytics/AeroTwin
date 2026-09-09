import simpy
import math

class VadodaraAirport:
    def __init__(self, env):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}

    def pushback_and_depart(self, flight_id, risk_score):
        """
        Simulates exact real-world WGS84 coordinates for Vadodara Airport (VABO):
        - Terminal Apron Stand 1: (Lat: 22.33550, Lng: 73.22600, Alt: 0m), Heading: 180°
        - Pushback to Taxiway Alpha: (Lat: 22.33470, Lng: 73.22520, Alt: 0m), Heading: 224°
        - Taxi along Taxiway Alpha curve to Runway 04 Hold-Short: (Lat: 22.33020, Lng: 73.22010, Alt: 0m)
        - Lineup on Runway 04 Threshold: (Lat: 22.32970, Lng: 73.21930, Alt: 0m), Heading: 044°
        - Takeoff Roll down Runway 04 Centerline (Heading 044°) to (Lat: 22.34120, Lng: 73.23150, Alt: 0m)
        - Rotation (Pitch up 14°) & Climb into 3D Sky: Altitude 0m -> 450m (approx 1,500 ft AGL)
        """
        # 1. Parked at VABO Terminal Apron Stand 1
        lat = 22.33550
        lng = 73.22600
        alt = 0.0
        heading = 180.0
        pitch = 0.0
        roll = 0.0
        speed = 0

        self.flights[flight_id] = {
            "id": flight_id,
            "lat": lat,
            "lng": lng,
            "altitude": alt,
            "heading": heading,
            "pitch": pitch,
            "roll": roll,
            "speed": speed,
            "status": "gate",
            "risk": risk_score
        }
        yield self.env.timeout(2.5)

        # 2. Pushback from Stand 1 onto Taxiway Alpha
        self.flights[flight_id]["status"] = "pushback"
        self.flights[flight_id]["speed"] = 5
        pushback_steps = 15
        target_lat = 22.33470
        target_lng = 73.22520
        for i in range(pushback_steps):
            t = (i + 1) / pushback_steps
            self.flights[flight_id]["lat"] = lat + (target_lat - lat) * t
            self.flights[flight_id]["lng"] = lng + (target_lng - lng) * t
            self.flights[flight_id]["heading"] = 180.0 + 44.0 * t  # Swing tail towards 224°
            yield self.env.timeout(0.2)

        lat = target_lat
        lng = target_lng
        yield self.env.timeout(1.0)

        # 3. Taxi along Taxiway Alpha toward Runway 04 Holding Point
        self.flights[flight_id]["status"] = "taxi"
        self.flights[flight_id]["speed"] = 18
        self.flights[flight_id]["heading"] = 224.0  # Taxiing southwest

        taxi_steps = 30
        target_lat = 22.33020
        target_lng = 73.22010
        for i in range(taxi_steps):
            t = (i + 1) / taxi_steps
            self.flights[flight_id]["lat"] = lat + (target_lat - lat) * t
            self.flights[flight_id]["lng"] = lng + (target_lng - lng) * t
            yield self.env.timeout(0.2)

        lat = target_lat
        lng = target_lng

        # 4. Holding Short of Runway 04
        self.flights[flight_id]["status"] = "holding"
        self.flights[flight_id]["speed"] = 0
        yield self.env.timeout(1.2)

        # 5. Enter & Line Up on Runway 04 Threshold (Heading 044°)
        with self.runway.request() as req:
            yield req

            self.flights[flight_id]["status"] = "lineup"
            self.flights[flight_id]["speed"] = 8
            target_lat = 22.32970
            target_lng = 73.21930
            self.flights[flight_id]["lat"] = target_lat
            self.flights[flight_id]["lng"] = target_lng
            self.flights[flight_id]["heading"] = 44.0  # Runway 04 alignment
            yield self.env.timeout(1.5)

            # 6. Takeoff Roll along Runway 04 Centerline (2,469m asphalt)
            self.flights[flight_id]["status"] = "takeoff_roll"
            roll_steps = 40
            start_lat = 22.32970
            start_lng = 73.21930
            end_roll_lat = 22.34120
            end_roll_lng = 73.23150

            for i in range(roll_steps):
                t = (i + 1) / roll_steps
                accel_t = t ** 1.6  # Realistic acceleration curve
                self.flights[flight_id]["lat"] = start_lat + (end_roll_lat - start_lat) * accel_t
                self.flights[flight_id]["lng"] = start_lng + (end_roll_lng - start_lng) * accel_t
                self.flights[flight_id]["speed"] = int(20 + 130 * t)  # 20 to 150 kts
                yield self.env.timeout(0.12)

            # 7. Rotation (Pitch up 12-14°) & Positive Rate of Climb into 3D Sky
            self.flights[flight_id]["status"] = "climb"
            climb_steps = 65
            climb_end_lat = 22.35650
            climb_end_lng = 73.24750

            for i in range(climb_steps):
                t = (i + 1) / climb_steps
                self.flights[flight_id]["lat"] = end_roll_lat + (climb_end_lat - end_roll_lat) * t
                self.flights[flight_id]["lng"] = end_roll_lng + (climb_end_lng - end_roll_lng) * t
                # Climb altitude smoothly from 0 to 420 meters (approx 1,400 ft AGL)
                self.flights[flight_id]["altitude"] = round(420.0 * (t ** 1.3), 1)
                self.flights[flight_id]["pitch"] = 13.0 if t < 0.65 else 10.0
                # Slight right bank on climb corridor
                if t > 0.3:
                    self.flights[flight_id]["heading"] = 44.0 + 3.0 * (t - 0.3)
                    self.flights[flight_id]["roll"] = 5.0
                self.flights[flight_id]["speed"] = int(150 + 90 * t)
                yield self.env.timeout(0.12)

        self.flights[flight_id]["status"] = "airborne"
