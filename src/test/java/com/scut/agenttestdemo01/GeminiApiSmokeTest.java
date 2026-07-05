package com.scut.agenttestdemo01;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@EnabledIfSystemProperty(named = "gemini.smoke", matches = "true")
@EnabledIfEnvironmentVariable(named = "GEMINI_API_KEY", matches = ".+")
class GeminiApiSmokeTest {

    @Autowired
    private ChatModel chatModel;
    @Value("${spring.ai.google.genai.api-key}")
    private String apiKey;

    @Test
    void apiKeyIsConfigured() {
        assertThat(apiKey).isNotBlank();
        assertThat(apiKey).doesNotContain("GEMINI_API_KEY");
    }
    @Test
    void geminiApiResponds() {
        String response = chatModel.call("Reply with one short English sentence saying the Gemini API works.");

        System.out.println("Gemini API response: " + response);

        assertThat(response).isNotBlank();
    }
}
