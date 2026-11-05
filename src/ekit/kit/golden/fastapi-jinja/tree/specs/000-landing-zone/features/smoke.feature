Feature: Landing zone smoke (golden core; must stay green in every feature's green run)

  Background:
    Given the application is running

  @SCN-000-01
  Scenario: Liveness answers and echoes the correlation id
    When I GET "/health/live" with header "X-Correlation-ID" set to "smoke-test-0001"
    Then the response status is 200
    And the response header "X-Correlation-ID" equals "smoke-test-0001"

  @SCN-000-02
  Scenario: An unknown API route is a problem document
    When I GET "/api/v1/no-such-route"
    Then the response status is 404
    And the response is a problem document with code "not_found"

  @SCN-000-03
  Scenario: Pages carry security headers
    When I GET "/"
    Then the response status is 200
    And the response header "Content-Security-Policy" is present
    And the response header "X-Content-Type-Options" equals "nosniff"
