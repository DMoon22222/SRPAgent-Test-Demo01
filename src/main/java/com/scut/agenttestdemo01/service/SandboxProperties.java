package com.scut.agenttestdemo01.service;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "sandbox")
public class SandboxProperties {

    private String mode = "local";
    private long timeoutMs = 5000;
    private Docker docker = new Docker();

    public String getMode() {
        return mode;
    }

    public void setMode(String mode) {
        this.mode = mode;
    }

    public long getTimeoutMs() {
        return timeoutMs;
    }

    public void setTimeoutMs(long timeoutMs) {
        this.timeoutMs = timeoutMs;
    }

    public Docker getDocker() {
        return docker;
    }

    public void setDocker(Docker docker) {
        this.docker = docker;
    }

    public static class Docker {
        private String image = "srp-code-sandbox:latest";
        private String memory = "256m";
        private String cpus = "1";
        private String pidsLimit = "64";

        public String getImage() {
            return image;
        }

        public void setImage(String image) {
            this.image = image;
        }

        public String getMemory() {
            return memory;
        }

        public void setMemory(String memory) {
            this.memory = memory;
        }

        public String getCpus() {
            return cpus;
        }

        public void setCpus(String cpus) {
            this.cpus = cpus;
        }

        public String getPidsLimit() {
            return pidsLimit;
        }

        public void setPidsLimit(String pidsLimit) {
            this.pidsLimit = pidsLimit;
        }
    }
}