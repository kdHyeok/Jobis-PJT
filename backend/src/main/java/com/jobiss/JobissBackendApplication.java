package com.jobiss;

import com.jobiss.config.JobissProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@EnableScheduling
@EnableConfigurationProperties(JobissProperties.class)
public class JobissBackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(JobissBackendApplication.class, args);
    }
}
