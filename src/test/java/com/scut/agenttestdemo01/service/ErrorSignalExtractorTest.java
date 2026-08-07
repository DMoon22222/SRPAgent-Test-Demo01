package com.scut.agenttestdemo01.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ErrorSignalExtractorTest {

    @Test
    void extractsJavaMissingSymbolAndLocation() {
        String log = """
                Main.java:7: error: cannot find symbol
                    System.out.println(answer);
                                       ^
                  symbol:   variable answer
                  location: class Main
                """;

        String summary = ErrorSignalExtractor.summarize(log);

        assertThat(summary).contains("cannot find symbol");
        assertThat(summary).contains("Main.java:7");
    }

    @Test
    void extractsPythonRuntimeSignals() {
        String log = """
                Traceback (most recent call last):
                  File "Main.py", line 3, in <module>
                    print(10 / 0)
                ZeroDivisionError: division by zero
                """;

        String summary = ErrorSignalExtractor.summarize(log);

        assertThat(summary).contains("ZeroDivisionError");
        assertThat(summary).contains("Main.py:3");
    }
}
