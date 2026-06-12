import React, { useState, useEffect } from "react";
import "./App.css";
import { v4 as uuidv4 } from "uuid";

function App() {
  // ---------------- State Management ----------------
  const [videoUrl, setVideoUrl] = useState("");
  const [name, setName] = useState("");
  const [vehicleNumber, setVehicleNumber] = useState("");
  const [customVehicleNumber, setCustomVehicleNumber] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [isValid, setIsValid] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [transactionId, setTransactionId] = useState(null);
  const [customVehicleValid, setCustomVehicleValid] = useState(true);
  const [stopDisabled, setStopDisabled] = useState(false);
  const [userInfo, setUserInfo] = useState({});
  const [statusMessage, setStatusMessage] = useState(""); // UI message

  // ---------------- Camera & Backend Mapping ----------------
  const backendUrls = {
    cam_1: "http://127.0.0.1:8000",
    cam_2: "http://127.0.0.1:8001",
  };

  const getBackendUrl = () => backendUrls[videoUrl] || "http://127.0.0.1:8000";

  // ---------------- Fetch user data ----------------
  useEffect(() => {
    fetch("http://127.0.0.1:9000/users")
      .then((res) => res.json())
      .then((data) => {
        const users = {};
        data.users.forEach((u) => {
          users[u.name] = {
            role: u.role,
            user_id: u.user_id,
            device_unique_id: u.device_unique_id,
            company_name: u.company_name,
            branch: u.branch,
            sub_branch: u.sub_branch,
            mail: u.mail,
          };
        });
        setUserInfo(users);
      })
      .catch(() => setStatusMessage("❌ Failed to load user list."));
  }, []);

  const nameOptions = Object.keys(userInfo);
  const vehicleOptions = ["TN 37 DB 6030", "TN 37 DE 1897", "TN 38 AT 6500"];
  const videoUrlOptions = ["cam_1", "cam_2"];

  // ---------------- Input Validation ----------------
  useEffect(() => {
    setIsValid(
      name !== "" &&
        videoUrl !== "" &&
        (vehicleNumber !== "" ||
          (customVehicleNumber !== "" && customVehicleValid))
    );
  }, [videoUrl, name, vehicleNumber, customVehicleNumber, customVehicleValid]);

  // ---------------- Handlers ----------------
  const handleCustomVehicleChange = (e) => {
    const input = e.target.value.toUpperCase();
    setCustomVehicleNumber(input);
    setVehicleNumber("");
    setCustomVehicleValid(/^[A-Z]{2} \d{2} [A-Z]{1,2} \d{1,4}$/.test(input));
  };

  const handleVehicleDropdownChange = (e) => {
    setVehicleNumber(e.target.value);
    setCustomVehicleNumber("");
    setCustomVehicleValid(true);
  };

  // ---------------- Start Detection ----------------
  const startDetection = async () => {
    if (!isValid) {
      setStatusMessage("❌ Please fill in all fields correctly.");
      return;
    }

    const selectedVehicle = vehicleNumber || customVehicleNumber;
    const newSessionId = uuidv4();
    const newTransactionId = uuidv4();
    const user = userInfo[name];

    if (!user) {
      setStatusMessage("❌ User not found in database.");
      return;
    }

    setSessionId(newSessionId);
    setTransactionId(newTransactionId);
    setIsDetecting(true);
    setStopDisabled(true);
    setStatusMessage("⏳ Starting detection...");

    try {
      const response = await fetch(`${getBackendUrl()}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          role: user.role,
          user_id: user.user_id,
          device_unique_id: user.device_unique_id,
          vehicle_number: selectedVehicle,
          video_url: videoUrl,
          session_id: newSessionId,
          transaction_id: newTransactionId,
        }),
      });

      // ----------- Error Handling --------------
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        const msg = err.detail || "Failed to start detection.";

        if (msg.includes("Another detection session")) {
          setStatusMessage("⚠️ Another detection session is already running.");
        } else if (msg.includes("Session already running")) {
          setStatusMessage("⚠️ This session is already active.");
        } else if (msg.includes("User not found")) {
          setStatusMessage("❌ User not found in system.");
        } else if (msg.includes("Camera")) {
          setStatusMessage("❌ Camera not streaming or offline.");
        } else {
          setStatusMessage("❌ " + msg);
        }

        setIsDetecting(false);
        setStopDisabled(false);
        return;
      }

      setStatusMessage("✅ Detection started successfully.");
      setTimeout(() => setStopDisabled(false), 15000);
    } catch {
      setStatusMessage("❌ Backend unreachable. Server may be offline.");
      setIsDetecting(false);
      setStopDisabled(false);
    }
  };

  // ---------------- Stop Detection ----------------
  const stopDetection = async () => {
    if (!sessionId || !transactionId) {
      setStatusMessage("❌ No active session available.");
      return;
    }

    setIsDetecting(false);
    setStatusMessage("⏳ Stopping detection...");

    try {
      const response = await fetch(`${getBackendUrl()}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          transaction_id: transactionId,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        const msg = err.detail || "Failed to stop session.";

        if (msg.includes("Session not found")) {
          setStatusMessage("⚠️ Detection is not running.");
        } else {
          setStatusMessage("❌ " + msg);
        }
        return;
      }

      setStatusMessage("🛑 Detection stopped successfully.");
    } catch {
      setStatusMessage("❌ Failed to contact backend.");
    }
  };

  // ---------------- CAMERA OFFLINE AUTO-DETECTION ----------------
  useEffect(() => {
    if (!sessionId || !isDetecting) return;

    const interval = setInterval(() => {
      fetch(`${getBackendUrl()}/count/${sessionId}`)
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));

            if (
              err.detail?.includes("Session not found") ||
              res.status === 404
            ) {
              setStatusMessage("❌ Camera offline / video not streaming.");
              setIsDetecting(false);
              clearInterval(interval);
            }
          }
        })
        .catch(() => {
          setStatusMessage("❌ Backend unreachable.");
        });
    }, 1500);

    return () => clearInterval(interval);
  }, [sessionId, isDetecting, videoUrl]);

  // ---------------- UI ----------------
  return (
    <div className="app-container">
      <header className="app-header">
        <h1>AI Object Detection</h1>
      </header>

      <div className="form-container">

        {/* Status Message */}
        {statusMessage && (
          <div className="status-box">{statusMessage}</div>
        )}

        {/* Video Source Dropdown */}
        <select
          className="input-field"
          value={videoUrl}
          onChange={(e) => setVideoUrl(e.target.value)}
        >
          <option value="">Select Video URL</option>
          {videoUrlOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>

        {/* Name Dropdown */}
        <select
          className="input-field"
          value={name}
          onChange={(e) => setName(e.target.value)}
        >
          <option value="">Select Name</option>
          {nameOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>

        {/* Vehicle Inputs */}
        <div className="vehicle-input-container">
          <select
            className="input-field vehicle-dropdown"
            value={vehicleNumber}
            onChange={handleVehicleDropdownChange}
            disabled={customVehicleNumber !== ""}
          >
            <option value="">Select Vehicle</option>
            {vehicleOptions.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>

          <input
            type="text"
            className={`input-field vehicle-textbox ${customVehicleValid ? "" : "invalid"}`}
            placeholder="Enter Vehicle Number"
            value={customVehicleNumber}
            onChange={handleCustomVehicleChange}
            disabled={vehicleNumber !== ""}
          />
        </div>

        {!customVehicleValid && (
          <p className="error-message">Invalid vehicle number format</p>
        )}

        {/* Buttons */}
        <div className="button-container">
          <button
            className="button start-button"
            onClick={startDetection}
            disabled={!isValid || isDetecting}
          >
            Start Detection
          </button>

          <button
            className="button stop-button"
            onClick={stopDetection}
            disabled={!isDetecting || stopDisabled}
          >
            Stop Detection
          </button>
        </div>

      </div>
    </div>
  );
}

export default App;
