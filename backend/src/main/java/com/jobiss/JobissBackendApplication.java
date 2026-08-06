package com.jobiss;

import com.jobiss.config.JobissProperties;
import com.jobiss.config.RepositoryProperties;
import com.jobiss.config.RecoveryProperties;
import com.jobiss.config.DataProtectionProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@EnableScheduling
@EnableConfigurationProperties({
        JobissProperties.class,
        RepositoryProperties.class,
        RecoveryProperties.class,
        DataProtectionProperties.class
})
public class JobissBackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(JobissBackendApplication.class, args);
    }
}
