// ==UserScript==
// @name         Stake Hybrid Claimer
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Connects to API and claims codes received via WebSocket
// @author       You
// @match        https://stake.com/*
// @grant        none
// @connect      localhost
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    // CONFIGURATION
    const API_URL = "ws://localhost:3000/ws"; // Change to your server URL
    const RECONNECT_DELAY = 5000;

    let ws = null;
    let isProcessing = false;

    function log(msg) {
        console.log(`[StakeHybrid] ${msg}`);
    }

    function connect() {
        log(`Connecting to ${API_URL}...`);
        ws = new WebSocket(API_URL);

        ws.onopen = () => {
            log("✅ Connected to API");
        };

        ws.onmessage = async (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "new_code") {
                    const code = data.code;
                    log(`🚨 New Code Received: ${code}`);
                    await handleClaim(code);
                }
            } catch (e) {
                log(`Error parsing message: ${e}`);
            }
        };

        ws.onclose = () => {
            log("❌ Disconnected. Reconnecting in 5s...");
            setTimeout(connect, RECONNECT_DELAY);
        };

        ws.onerror = (err) => {
            log(`❌ WebSocket Error: ${err}`);
        };
    }

    async function handleClaim(code) {
        if (isProcessing) {
            log("⏳ Already processing a claim. Skipping...");
            return;
        }
        isProcessing = true;

        try {
            // 1. Navigate to the claim page
            const targetUrl = `https://stake.com/zh/settings/offers?type=drop&code=${code}&modal=redeemBonus`;
            if (window.location.href !== targetUrl) {
                log(`🔄 Navigating to claim page...`);
                window.location.href = targetUrl;
                // Wait for page to load (simple wait, can be improved)
                await new Promise(r => setTimeout(r, 3000));
            }

            // 2. Solve Turnstile (Simplified - you need to implement the actual solver logic here)
            // In a real scenario, you would use a library or your own logic to get the token
            log("🔐 Solving Turnstile...");
            
            // Wait for Turnstile iframe
            const iframe = await waitForElement("iframe[src*='turnstile']", 10000);
            if (!iframe) {
                throw new Error("Turnstile iframe not found");
            }

            // Get Token (This is the tricky part - depends on how Turnstile exposes it)
            // This is a placeholder. You need to implement the actual token extraction.
            const token = await getTurnstileToken();
            if (!token) {
                throw new Error("Failed to get Turnstile token");
            }

            log(`✅ Token obtained: ${token.substring(0, 10)}...`);

            // 3. Execute Claim
            await submitClaim(code, token);

        } catch (error) {
            log(`❌ Claim failed: ${error.message}`);
        } finally {
            isProcessing = false;
        }
    }

    function waitForElement(selector, timeout) {
        return new Promise((resolve) => {
            if (document.querySelector(selector)) {
                return resolve(document.querySelector(selector));
            }

            const observer = new MutationObserver(() => {
                if (document.querySelector(selector)) {
                    observer.disconnect();
                    resolve(document.querySelector(selector));
                }
            });

            observer.observe(document.body, { childList: true, subtree: true });

            setTimeout(() => {
                observer.disconnect();
                resolve(null);
            }, timeout);
        });
    }

    async function getTurnstileToken() {
        // This requires accessing the Turnstile widget inside the iframe
        // or using the global turnstile object if available.
        // NOTE: This is complex and requires careful implementation to avoid detection.
        // For now, we assume the global 'turnstile' object is available after page load.
        
        return new Promise((resolve) => {
            if (typeof turnstile !== 'undefined') {
                const widgets = turnstile.getWidgetIds();
                if (widgets.length > 0) {
                    const token = turnstile.getResponse(widgets[0]);
                    if (token) {
                        resolve(token);
                    } else {
                        // Wait for token
                        const interval = setInterval(() => {
                            const t = turnstile.getResponse(widgets[0]);
                            if (t) {
                                clearInterval(interval);
                                resolve(t);
                            }
                        }, 100);
                        setTimeout(() => clearInterval(interval), 10000);
                    }
                } else {
                    resolve(null);
                }
            } else {
                resolve(null);
            }
        });
    }

    async function submitClaim(code, token) {
        const payload = {
            query: `mutation ClaimConditionBonusCode($code: String!, $currency: CurrencyEnum!, $turnstileToken: String!) {
                claimConditionBonusCode(code: $code, currency: $currency, turnstileToken: $turnstileToken) {
                    bonusCode { id code }
                    amount
                    currency
                }
            }`,
            variables: {
                code: code,
                currency: "usdt",
                turnstileToken: token
            }
        };

        try {
            const response = await fetch("https://stake.com/_api/graphql", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Origin": "https://stake.com"
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (data.data && data.data.claimConditionBonusCode) {
                log(`✅ SUCCESS! Claimed ${data.data.claimConditionBonusCode.amount} ${data.data.claimConditionBonusCode.currency}`);
                // Optionally send success back to server
                // ws.send(JSON.stringify({ type: "claim_success", code: code }));
            } else {
                log(`❌ Claim failed: ${JSON.stringify(data.errors)}`);
            }
        } catch (e) {
            log(`❌ Network error: ${e.message}`);
        }
    }

    // Start connection
    connect();

})();