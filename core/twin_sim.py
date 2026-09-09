import simpy
import math

class VadodaraAirport:
    def __init__(self, env):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}

    def pushback_and_depart(self, flight_id, risk_score):
        """
        Simulates accurate 3D trajectory for Vadodara Airport (VABO):
        - Apron Stand 1: (x: -30, y: 0.5, z: -15), Heading 180°
        - Pushback: Reverse to taxiway centerline (x: -30, y: 0.5, z: -40), turns to heading 225°
        - Taxi: Taxis along Taxiway Alpha to Runway 04 Threshold at (x: -90, y: 0.5, z: -90)
        - Takeoff Roll: Lines up on Runway 04 centerline (heading 45°), accelerates down to (x: 50, z: 50)
        - Rotation & Climb: Pitches nose up 14°, climbs through altitude (y: 0.5 -> 60), accelerates to cruise climb
        """
        # 1. Gate Stand 1 (Parked)
        self.flights[flight_id] = {
            "id": flight_id,
            "x": -30.0,
            "y": 0.5,
            "z": -15.0,
            "heading": math.pi,  # Facing away from terminal
            "pitch": 0.0,
            "roll": 0.0,
            "speed": 0,
            "altitude": 0,
            "status": "gate",
            "risk": risk_score
        }
        yield self.env.timeout(2)

        # 2. Pushback
        self.flights[flight_id]["status"] = "pushback"
        self.flights[flight_id]["speed"] = 5
        steps = 15
        for i in range(steps):
            # Reverse straight back, then swing tail
            progress = i / steps
            self.flights[flight_id]["z"] -= 25.0 / steps
            self.flights[flight_id]["heading"] = math.pi + (math.pi / 4.0) * progress
            yield self.env.timeout(0.2)

        yield self.env.timeout(1)

        # 3. Taxi along Taxiway Alpha to Runway 04 Threshold (-90, -90)
        self.flights[flight_id]["status"] = "taxi"
        self.flights[flight_id]["heading"] = -3.0 * math.pi / 4.0  # 225° towards R04 threshold
        self.flights[flight_id]["speed"] = 15

        start_x, start_z = self.flights[flight_id]["x"], self.flights[flight_id]["z"]
        target_x, target_z = -90.0, -90.0
        taxi_steps = 35
        for i in range(taxi_steps):
            t = (i + 1) / taxi_steps
            self.flights[flight_id]["x"] = start_x + (target_x - start_x) * t
            self.flights[flight_id]["z"] = start_z + (target_z - start_z) * t
            yield self.env.timeout(0.2)

        # 4. Holding Short / Queue for Runway 04
        self.flights[flight_id]["status"] = "holding"
        self.flights[flight_id]["speed"] = 0
        yield self.env.timeout(1)

        with self.runway.request() as req:
            yield req

            # Line up on Runway 04 Centerline (-85, -85) facing heading 45°
            self.flights[flight_id]["status"] = "lineup"
            self.flights[flight_id]["x"] = -85.0
            self.flights[flight_id]["z"] = -85.0
            self.flights[flight_id]["heading"] = math.pi / 4.0  # 45 degrees
            yield self.env.timeout(1)

            # 5. Takeoff Roll down Runway 04
            self.flights[flight_id]["status"] = "takeoff_roll"
            roll_steps = 40
            for i in range(roll_steps):
                t = (i + 1) / roll_steps
                # Quadratic acceleration
                dist = 140.0 * (t ** 1.6)
                self.flights[flight_id]["x"] = -85.0 + (dist * math.sin(math.pi / 4.0))
                self.flights[flight_id]["z"] = -85.0 + (dist * math.cos(math.pi / 4.0))
                self.flights[flight_id]["speed"] = int(20 + 130 * t)  # 20 to 150 kts
                yield self.env.timeout(0.15)

            # 6. Rotate & Initial Climb (Lift-off)
            self.flights[flight_id]["status"] = "climb"
            climb_steps = 60
            for i in range(climb_steps):
                t = (i + 1) / climb_steps
                self.flights[flight_id]["x"] += 3.5 * math.sin(math.pi / 4.0)
                self.flights[flight_id]["z"] += 3.5 * math.cos(math.pi / 4.0)
                # Climb altitude smoothly
                self.flights[flight_id]["y"] = 0.5 + 55.0 * (t ** 1.3)
                self.flights[flight_id]["altitude"] = int(self.flights[flight_id]["y"] * 50)  # Feet AGL
                # Pitch up 12-15 degrees during rotation and climb
                self.flights[flight_id]["pitch"] = 0.22 if t < 0.7 else 0.15
                # Slight banking roll to follow departure routing
                if t > 0.4:
                    self.flights[flight_id]["heading"] += 0.005
                    self.flights[flight_id]["roll"] = 0.08
                self.flights[flight_id]["speed"] = int(150 + 90 * t)
                yield self.env.timeout(0.15)

        self.flights[flight_id]["status"] = "airborne"
