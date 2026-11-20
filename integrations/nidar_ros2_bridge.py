#!/usr/bin/env python3
"""Relay ROS 2 mission outputs to the local NIDAR GCS (no flight control)."""
import json
import math
import os
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


def xy(point):
    return {"x": point.x, "y": point.y}


class Relay(Node):
    def __init__(self):
        super().__init__("nidar_gcs_relay")
        self.url = os.environ.get("NIDAR_GCS_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/nidar"
        self.token = os.environ["NIDAR_BRIDGE_TOKEN"]
        self.http = build_opener(ProxyHandler({}))
        self.map = self.pose = self.mission = self.frame = None
        self.sequence = int(time.monotonic_ns())
        self.last_error = 0.0
        self.commands = self.create_publisher(String, "/nidar/operator_request", 10)
        self.create_subscription(OccupancyGrid, "/nidar/map", self.on_map, 10)
        self.create_subscription(PoseStamped, "/nidar/pose", self.on_pose, qos_profile_sensor_data)
        self.create_subscription(CompressedImage, "/nidar/camera/compressed", self.on_frame, qos_profile_sensor_data)
        self.create_subscription(String, "/nidar/mission", self.on_mission, 10)
        self.create_timer(0.5, self.publish_snapshot)
        self.create_timer(0.12, self.publish_frame)

    def on_map(self, msg):
        q = msg.info.origin.orientation
        if msg.header.frame_id != "map" or abs(q.x) + abs(q.y) + abs(q.z) > 1e-6 or abs(abs(q.w) - 1) > 1e-6:
            self.warn("Expected an axis-aligned occupancy grid in the map frame.")
            return
        self.map = {"width": msg.info.width, "height": msg.info.height,
                    "resolution_m": msg.info.resolution, "origin": xy(msg.info.origin.position),
                    "cells": [-1 if p < 0 else 100 if p >= 50 else 0 for p in msg.data]}

    def on_pose(self, msg):
        if msg.header.frame_id != "map":
            self.warn("Expected drone pose already transformed into the map frame.")
            return
        q = msg.pose.orientation
        self.pose = {**xy(msg.pose.position),
                     "yaw_rad": math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y ** 2 + q.z ** 2))}

    def on_frame(self, msg):
        if "jpeg" in msg.format.lower() or "jpg" in msg.format.lower():
            self.frame = bytes(msg.data)

    def on_mission(self, msg):
        try:
            value = json.loads(msg.data)
            if not isinstance(value, dict) or not isinstance(value.get("mission_id"), str):
                raise ValueError("mission_id is required")
        except ValueError as exc:
            self.warn(f"Invalid mission state: {exc}")
            return
        if self.mission and value["mission_id"] != self.mission["mission_id"]:
            self.map = self.pose = self.frame = None
        self.mission = value
        self.mission_at = time.monotonic()

    def warn(self, message):
        if time.monotonic() - self.last_error > 2:
            self.get_logger().warning(message)
            self.last_error = time.monotonic()

    def put(self, path, payload, content_type):
        request = Request(self.url + path, data=payload, method="PUT", headers={
            "Content-Type": content_type, "X-Nidar-Token": self.token})
        with self.http.open(request, timeout=0.3) as result:
            return result.read()

    def publish_snapshot(self):
        if not self.mission or time.monotonic() - self.mission_at > 2:
            return
        self.sequence += 1
        payload = {**self.mission, "sequence": self.sequence, "pose": self.pose, "map": self.map}
        try:
            response = json.loads(self.put("/snapshot", json.dumps(payload, allow_nan=False).encode(), "application/json"))
            if response["pending_command"]:
                self.commands.publish(String(data=json.dumps(response["pending_command"])))
        except (OSError, URLError, ValueError) as exc:
            self.warn(f"Snapshot relay failed: {exc}")

    def publish_frame(self):
        if self.frame is None or not self.mission or time.monotonic() - self.mission_at > 2:
            return
        frame, self.frame = self.frame, None
        try:
            self.put(f"/camera/{quote(self.mission['mission_id'], safe='')}", frame, "image/jpeg")
        except (OSError, URLError) as exc:
            self.warn(f"Camera relay failed: {exc}")


def main():
    rclpy.init()
    try:
        relay = Relay()
        try:
            rclpy.spin(relay)
        finally:
            relay.destroy_node()
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
