/**
 * OpenClaw Bridge
 * Routes tool calls from Gemini to OpenClaw Gateway
 */

export class OpenClawBridge {
    constructor(host, port, token) {
        this.host = host;
        this.port = port;
        this.token = token;
        this.baseUrl = `${host}:${port}`;
    }

    /**
     * Execute a task via OpenClaw
     * @param {string} task - Natural language description of the task
     * @returns {Promise<object>} - Result from OpenClaw
     */
    async execute(task) {
        try {
            const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.token}`
                },
                body: JSON.stringify({
                    model: 'default',
                    messages: [
                        {
                            role: 'user',
                            content: task
                        }
                    ],
                    // Request tool execution
                    tool_choice: 'auto'
                })
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`OpenClaw request failed: ${response.status} - ${errorText}`);
            }

            const result = await response.json();
            
            // Extract the response content
            if (result.choices && result.choices[0] && result.choices[0].message) {
                return {
                    success: true,
                    result: result.choices[0].message.content
                };
            }

            return {
                success: true,
                result: 'Task completed'
            };

        } catch (error) {
            console.error('OpenClaw execution error:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Check if OpenClaw gateway is reachable
     * @returns {Promise<boolean>}
     */
    async healthCheck() {
        try {
            const response = await fetch(`${this.baseUrl}/health`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });
            return response.ok;
        } catch (error) {
            console.error('OpenClaw health check failed:', error);
            return false;
        }
    }
}
