// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 32100050, 32100051, 2, 32100200, 32100202, 32100203, 32102405, 32102406, 32102407, 32102410, 32102411, 32102412, 32102415, 32102416, 32102417, 32102420, 32102421, 32102422, 32102400);
    $InitializeCommonEvent(0, 90015301, 32105300, 32100200, 32100201, 32100202, 32100203, 2);
    $InitializeCommonEvent(0, 90015306, 32106500);
    $InitializeCommonEvent(0, 90015303, 32102401);
    $InitializeCommonEvent(0, 90015305, 32102430, 32102431, 32102432, 32102433);
    $InitializeCommonEvent(0, 90015304, 32100050, 32100200, 32100202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 32100051, 32100200, 32100203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32100800, 32102800, 30, 903460500, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32100800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32100800, 32102800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32100800, 32102800, 30, 903460500, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32100800, 32102800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32100800, 32100800, 1030, 940000, 11200, 903460500, 32100800);
    $InitializeCommonEvent(0, 90015006, 32101500, 32100500, 32100800, 5);
    $InitializeCommonEvent(0, 90015005, 32101500, 32102800, 32100800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32100800, 940000, 32100800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 32100800, 940000, 32100800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 32100800, 8165);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32105810, 32102810, 30, 904354000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32105810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32105810, 32102810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32105810, 32102810, 30, 904354000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32105810, 32102810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32100810, 32105810, 1030, 940000, 11200, 904354000, 32100510);
    $InitializeCommonEvent(0, 90015006, 32101510, 32100510, 32100810, 5);
    $InitializeCommonEvent(0, 90015005, 32101510, 32102810, 32100810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32100810, 940000, 32105810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 32100810, 940000, 32105810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 32100810, 8165);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32105820, 32102820, 30, 904353000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32105820, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32105820, 32102820, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32105820, 32102820, 30, 904353000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32105820, 32102820, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32100820, 32105820, 1030, 940000, 11200, 904353000, 32100520);
    $InitializeCommonEvent(0, 90015006, 32101520, 32100520, 32100820, 5);
    $InitializeCommonEvent(0, 90015005, 32101520, 32102820, 32100820);
    GotoIf(S6, Signed(0) != 0);
    GotoIf(S6, 0 != 0);
    Goto(S8);
S6:
    GotoIf(S7, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32100820, 940000, 32105820, 0, 0);
    Goto(S8);
S7:
    $InitializeCommonEvent(0, 90015008, 0, 32100820, 940000, 32105820, 0, 0);
S8:
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015050, 32100820, 8165);
    }
    $InitializeCommonEvent(0, 90035280, 32102491, 32100700, 32100701, 32100702, 8060, 0, 32100800, 32100810, 32100820, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32102491, 32100700, 32100701, 32100702, 80010, 0, 32100800, 32100810, 32100820, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32102491, 32100700, 32100701, 32100702, 80011, 1, 32100800, 32100810, 32100820, 0, 0);
    $InitializeCommonEvent(0, 90035281, 32102491, 32100700, 32100701, 32100702, 80011, 32100800, 32100810, 32100820, 0, 0);
    $InitializeCommonEvent(0, 90035282, 32100490, 32102490, 32100700, 32100701, 32100702, 32100703);
    $InitializeCommonEvent(0, 90035283, 32100490, 32102491, 32101690, 32100700, 32100701, 32100702, 32100704, 32100705, 32100706);
    $InitializeCommonEvent(0, 90035284, 32105490, 32105491, 32100700, 32100702, 32100705, 32100706);
    $InitializeCommonEvent(0, 90035285, 32100490, 32100700, 32100701, 32100702, 32100705, 32100706);
    $InitializeCommonEvent(0, 90035286, 32100490, 32102491, 32100700, 32100701, 32100702, 32100705, 32100706);
    $InitializeCommonEvent(0, 90035288, 32102491, 32100700, 32100702, 32100705, 32100706);
    $InitializeCommonEvent(0, 90015000, 32100704, 32100490, 907640001, 50, 0, 32100706);
    $InitializeCommonEvent(0, 99055500, 32100490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 32100704, 32100705, 32100490, 1020, 0, -1, -1, 32100490, 0);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 32100800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 32100810);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 2, 32100820);
});
