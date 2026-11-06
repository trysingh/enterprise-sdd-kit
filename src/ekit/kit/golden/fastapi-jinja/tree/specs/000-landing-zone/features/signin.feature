Feature: Day-0 dev-user seam (golden core; also the self-test of the journey step library)

  @J-000 @SCN-000-04
  Scenario Outline: <user> signs in as a dev user and calls the API by operation id
    Given I am signed in as "<user>"
    When I call "health_live"
    Then the call succeeds
    And the response contains "ok"
    And I remember "status" from the response as "health"
    And the response contains the remembered "health"

    Examples:
      | user  |
      | asha  |
      | ravi  |

  @SCN-000-05
  Scenario: The sign-in page for dev users renders
    Given the application is running
    When I open the page "/signin"
    Then the response status is 200
    And the page contains "Sign in"
