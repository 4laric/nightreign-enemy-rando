// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 34300050, 34300051, 2, 34300200, 34300202, 34300203, 34302405, 34302406, 34302407, 34302410, 34302411, 34302412, 34302415, 34302416, 34302417, 34302420, 34302421, 34302422, 34302400);
    $InitializeCommonEvent(0, 90015301, 34305300, 34300200, 34300201, 34300202, 34300203, 2);
    $InitializeCommonEvent(0, 90015306, 34306500);
    $InitializeCommonEvent(0, 90015303, 34302401);
    $InitializeCommonEvent(0, 90015305, 34302430, 34302431, 34302432, 34302433);
    $InitializeCommonEvent(0, 90015304, 34300050, 34300200, 34300202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 34300051, 34300200, 34300203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34305800, 34302800, 30, 903970313, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34305800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34305800, 34302800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34305800, 34302800, 30, 903970313, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34305800, 34302800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34300800, 34305800, 1030, 940000, 11200, 903970313, 34300500);
    $InitializeCommonEvent(0, 90015006, 34301500, 34300500, 34300800, 5);
    $InitializeCommonEvent(0, 90015005, 34301500, 34302800, 34300800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34300800, 940000, 34305800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 34300800, 940000, 34305800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 34300800, 8170);
    }
    $InitializeCommonEvent(0, 90035280, 34302491, 34300700, 34300701, 34300702, 8060, 0, 34300800, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 34302491, 34300700, 34300701, 34300702, 80010, 0, 34300800, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 34302491, 34300700, 34300701, 34300702, 80011, 1, 34300800, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 34302491, 34300700, 34300701, 34300702, 80011, 34300800, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 34300490, 34302490, 34300700, 34300701, 34300702, 34300703);
    $InitializeCommonEvent(0, 90035283, 34300490, 34302491, 34301690, 34300700, 34300701, 34300702, 34300704, 34300705, 34300706);
    $InitializeCommonEvent(0, 90035284, 34305490, 34305491, 34300700, 34300702, 34300705, 34300706);
    $InitializeCommonEvent(0, 90035285, 34300490, 34300700, 34300701, 34300702, 34300705, 34300706);
    $InitializeCommonEvent(0, 90035286, 34300490, 34302491, 34300700, 34300701, 34300702, 34300705, 34300706);
    $InitializeCommonEvent(0, 90035288, 34302491, 34300700, 34300702, 34300705, 34300706);
    $InitializeCommonEvent(0, 90015000, 34300704, 34300490, 907640001, 50, 0, 34300706);
    $InitializeCommonEvent(0, 99055500, 34300490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 34300704, 34300705, 34300490, 1020, 0, -1, -1, 34300490, 0);
    $InitializeCommonEvent(0, 90005526, 34300500, 34301200);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 34300800);
});
