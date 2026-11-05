Feature: Reference slice - greeting (exemplar; copy the shape, never the names or ids)

  Background:
    Given the application is running

  @SCN-000-11
  Scenario: A greeting is returned for a name
    When I GET "/api/v1/reference/greeting?name=Ada"
    Then the response status is 200
    And the response JSON field "message" equals "Hello, Ada"

  @SCN-000-12
  Scenario: A missing name is a validation problem
    When I GET "/api/v1/reference/greeting"
    Then the response status is 422
    And the response is a problem document with code "validation_failed"

  @SCN-000-13
  Scenario: The greeting page escapes what it shows
    When I GET "/reference?name=<b>Ada</b>"
    Then the response status is 200
    And the page contains "Hello, &lt;b&gt;Ada&lt;/b&gt;"

  @SCN-000-14
  Scenario: A greeting names the visitor who asked
    Given a visitor called "Grace"
    When the visitor asks for a greeting
    Then the greeting names the visitor

  @SCN-000-15
  Scenario: The greeting form posts with its CSRF token
    When I POST the form "name=Ada" to "/reference"
    Then the response status is 200
    And the page contains "Hello, Ada"

  @SCN-000-16
  Scenario: A form post without the CSRF token is refused
    When I POST JSON {"name": "Ada"} to "/reference"
    Then the response status is 403
    And the response is a problem document with code "forbidden"
